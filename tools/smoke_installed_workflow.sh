#!/usr/bin/env bash
# Verify a packaged backend in a clean runtime without system Python.
set -euo pipefail

sidecar="${1:-/usr/bin/nova-backend}"
run_dir="$(mktemp -d /tmp/nova-installed-workflow.XXXXXX)"
export NOVA_SESSION_TOKEN=temporary-qualification-session
"${sidecar}" --port 0 --data-dir "${run_dir}" >"${run_dir}/backend.log" 2>&1 &
backend_pid=$!
cleanup() {
  if kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
  wait "${backend_pid}" 2>/dev/null || true
}
trap cleanup EXIT

endpoint=''
for _ in {1..30}; do
  endpoint="$(sed -n 's/^NOVA_BACKEND_ENDPOINT=//p' "${run_dir}/backend.log" | head -n1)"
  if [[ -n "${endpoint}" ]] && curl --fail --silent "${endpoint}/health" >/dev/null; then
    break
  fi
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    cat "${run_dir}/backend.log" >&2
    exit 1
  fi
  sleep 1
done
[[ -n "${endpoint}" ]]
header=(--header "X-Nova-Session: ${NOVA_SESSION_TOKEN}" --header 'Content-Type: application/json')
request() {
  curl --fail --silent --show-error "${header[@]}" "${endpoint}$1" "${@:2}"
}
asset_id="$(request /v1/assets/demonstration-polar --data '{"airfoil":"NACA 4412"}' | jq -er .id)"
request /v1/workflow-template >"${run_dir}/workflow.json"
jq -n --slurpfile workflow "${run_dir}/workflow.json" --arg asset "${asset_id}" '{
  name:"Installed package workflow", workflow:$workflow[0], polar_asset_id:$asset, conditions:{},
  inputs:{project_name:"Installed package workflow", propeller_type:"traditional", thrust_target:2,
    rpm:5000, diameter:0.25, blades:2, airfoil:"NACA 4412", geometry_method:"bezier", airfoil_assignments:[],
    geometry_parameters:{
      chord_points:[{x:0,y:0.026},{x:0.33,y:0.029},{x:0.72,y:0.016},{x:1,y:0.006}],
      twist_points:[{x:0,y:34},{x:0.33,y:25},{x:0.72,y:14},{x:1,y:7}]}}}' >"${run_dir}/project.json"
project_id="$(request /v1/projects --data-binary @"${run_dir}/project.json" | jq -er .id)"
jq --arg id "${project_id}" '. + {id:$id}' "${run_dir}/project.json" >"${run_dir}/run.json"
run_id="$(request /v1/runs --data-binary @"${run_dir}/run.json" | jq -er .id)"
for _ in {1..30}; do
  request "/v1/runs/${run_id}" >"${run_dir}/result.json"
  state="$(jq -r .state "${run_dir}/result.json")"
  case "${state}" in
    succeeded) break ;;
    failed|cancelled|interrupted) cat "${run_dir}/result.json" >&2; exit 1 ;;
  esac
  sleep 1
done
jq -e '.state == "succeeded" and .result.analyses[0].convergence.converged and .result.analyses[0].performance.thrust_n > 0' "${run_dir}/result.json" >/dev/null
request "/v1/runs/${run_id}/stl" >"${run_dir}/propeller.stl"
[[ "$(wc -c <"${run_dir}/propeller.stl")" -gt 1000 ]]
request "/v1/projects/${project_id}/archive" >"${run_dir}/project.nova"
base64 -w0 "${run_dir}/project.nova" | jq -Rs '{content_base64:.}' >"${run_dir}/import.json"
imported_id="$(request /v1/projects/import --data-binary @"${run_dir}/import.json" | jq -er .id)"
[[ "${imported_id}" != "${project_id}" ]]
request "/v1/projects/${imported_id}" | jq -e '.inputs.rpm == 5000 and .workflow.template_origin == "propeller-v1"' >/dev/null
jq --arg id "${project_id}" '. + {id:$id, study:{parameter:"rpm",values:[3500,5000],secondary:{parameter:"air_density_kg_m3",values:[1.1,1.225]}}}' "${run_dir}/project.json" >"${run_dir}/study.json"
study_id="$(request /v1/studies --data-binary @"${run_dir}/study.json" | jq -er .id)"
for _ in {1..30}; do
  request "/v1/runs/${study_id}" >"${run_dir}/study-result.json"
  state="$(jq -r .state "${run_dir}/study-result.json")"
  case "${state}" in
    succeeded) break ;;
    failed|cancelled|interrupted) cat "${run_dir}/study-result.json" >&2; exit 1 ;;
  esac
  sleep 1
done
jq -e '.state == "succeeded" and .result.completed_cases == 4 and .result.failed_cases == 0' "${run_dir}/study-result.json" >/dev/null
request "/v1/runs/${study_id}/study.rows" | jq -e '(.axes | length)==2 and (.rows | length)==4 and .rows[0].secondary_parameter=="air_density_kg_m3"' >/dev/null
request "/v1/runs/${study_id}/study.csv" >"${run_dir}/study.csv"
[[ -s "${run_dir}/study.csv" ]]
jq -n --arg original "${run_id}" --arg study "${study_id}" '{run_ids:[$original,$study]}' >"${run_dir}/comparison.json"
request /v1/runs/compare --data-binary @"${run_dir}/comparison.json" | jq -e '.rows | length == 5' >/dev/null
jq --arg id "${project_id}" '. + {project_id:$id,name:"Shared BEMT baseline"}' "${run_dir}/project.json" >"${run_dir}/simulation.json"
request /v1/simulations --data-binary @"${run_dir}/simulation.json" >"${run_dir}/simulation-saved.json"
simulation_id="$(jq -er .id "${run_dir}/simulation-saved.json")"
geometry_id="$(jq -er .geometry_id "${run_dir}/simulation-saved.json")"
request "/v1/simulations/${simulation_id}/clone" --data '{"name":"Shared LLT variant"}' >"${run_dir}/variant-cloned.json"
jq -n --slurpfile first "${run_dir}/simulation-saved.json" --slurpfile second "${run_dir}/variant-cloned.json" '{name:"Installed frozen comparison",simulations:[$first[0],$second[0]] | map({id,expected_revision:.revision})}' >"${run_dir}/batch.json"
batch_id="$(request "/v1/projects/${project_id}/comparisons" --data-binary @"${run_dir}/batch.json" | jq -er .id)"
for _ in {1..30}; do
  request "/v1/runs/${batch_id}" >"${run_dir}/batch-result.json"
  state="$(jq -r .state "${run_dir}/batch-result.json")"
  case "${state}" in
    succeeded) break ;;
    failed|cancelled|interrupted) cat "${run_dir}/batch-result.json" >&2; exit 1 ;;
  esac
  sleep 1
done
jq -e '.state=="succeeded" and (.result.rows | length)==2 and .result.rows[1].baseline_differences_pct.thrust_n==0' "${run_dir}/batch-result.json" >/dev/null
request "/v1/runs/${batch_id}/comparison.csv" >"${run_dir}/batch.csv"
[[ -s "${run_dir}/batch.csv" ]]
jq '{name,inputs,workflow,polar_asset_id,conditions,project_id,id,expected_revision:.revision} | .workflow.nodes[3].config.model="llt" | .inputs.rpm=6500' "${run_dir}/variant-cloned.json" >"${run_dir}/variant.json"
request /v1/simulations --data-binary @"${run_dir}/variant.json" >"${run_dir}/variant-saved.json"
variant_id="$(jq -er .id "${run_dir}/variant-saved.json")"
jq -e --arg id "${geometry_id}" '.geometry_id==$id and .geometry_revision==1' "${run_dir}/variant-saved.json" >/dev/null
request "/v1/simulations/${variant_id}/run" --data '{"expected_revision":2}' >"${run_dir}/variant-run.json"
variant_run_id="$(jq -er .id "${run_dir}/variant-run.json")"
for _ in {1..30}; do
  request "/v1/runs/${variant_run_id}" >"${run_dir}/variant-result.json"
  state="$(jq -r .state "${run_dir}/variant-result.json")"
  case "${state}" in
    succeeded) break ;;
    failed|cancelled|interrupted) cat "${run_dir}/variant-result.json" >&2; exit 1 ;;
  esac
  sleep 1
done
jq -e '.state=="succeeded" and .result.analyses[0].model=="llt" and .geometry_revision==1 and .result.geometry.diameter_m==0.25' "${run_dir}/variant-result.json" >/dev/null
jq --arg gid "${geometry_id}" '{name:"Shared rotor",inputs,geometry_id:$gid,expected_geometry_revision:1} | .inputs.diameter=0.27' "${run_dir}/project.json" >"${run_dir}/geometry-revision.json"
request "/v1/projects/${project_id}/geometries" --data-binary @"${run_dir}/geometry-revision.json" | jq -e '.geometry_revision==2' >/dev/null
jq -n --arg id "${variant_id}" '{geometry_revision:2,simulations:[{id:$id,expected_revision:2}]}' >"${run_dir}/geometry-adoption.json"
request "/v1/projects/${project_id}/geometries/${geometry_id}/adopt" --data-binary @"${run_dir}/geometry-adoption.json" | jq -e '.simulations[0].geometry_revision==2 and .simulations[0].inputs.rpm==6500' >/dev/null
request "/v1/simulations/${simulation_id}" | jq -e '.geometry_revision==1 and .revision==1 and .inputs.diameter==0.25' >/dev/null
request "/v1/runs/${variant_run_id}" | jq -e '.geometry_revision==1 and .inputs.diameter==0.25 and .result.geometry.diameter_m==0.25' >/dev/null
request "/v1/projects/${project_id}/archive" >"${run_dir}/shared-geometry.nova"
base64 -w0 "${run_dir}/shared-geometry.nova" | jq -Rs '{content_base64:.}' >"${run_dir}/shared-geometry-import.json"
shared_import_id="$(request /v1/projects/import --data-binary @"${run_dir}/shared-geometry-import.json" | jq -er .id)"
request "/v1/projects/${shared_import_id}/geometries" | jq -e 'length==2' >/dev/null
request "/v1/projects/${shared_import_id}/simulations" | jq -e 'map(.geometry_id) | unique | length==1' >/dev/null
request /v1/adapters | jq -e 'map(.id) | sort == ["openfast", "pywake"]' >/dev/null
jq -n '{name:"Installed PyWake inputs",demonstration:true,case:{wake_model:"noj",
  turbine:{name:"Fixture",diameter_m:80,hub_height_m:100,wind_speed_m_s:[0,5,10,25],power_w:[0,100,1000,1000],ct:[0.8,0.8,0.8,0.1]},
  layout:{x_m:[0],y_m:[0]},wind:{directions_deg:[270],speeds_m_s:[5,10],probabilities:[[0.5,0.5]],turbulence_intensity:0.1}}}' >"${run_dir}/saved-external-case.json"
saved_case_id="$(request /v1/external-cases --data-binary @"${run_dir}/saved-external-case.json" | jq -er .id)"
request "/v1/external-cases/${saved_case_id}" | jq -e '.demonstration and .case.wind.probabilities==[[0.5,0.5]] and .adapter_id=="pywake"' >/dev/null
cat >"${run_dir}/source.out" <<'DATA'
NOVA original integration fixture
Time GenPwr
(s) (kW)
0 10
1 20
DATA
base64 -w0 "${run_dir}/source.out" | jq -Rs '{filename:"sample.out",content_base64:.}' >"${run_dir}/output-import.json"
external_id="$(request /v1/openfast/import --data-binary @"${run_dir}/output-import.json" | jq -er .id)"
request "/v1/runs/${external_id}" | jq -e '.result.data.values == [[10],[20]] and .result.data.channels[0].units == "(kW)"' >/dev/null
request "/v1/external-runs/${external_id}/csv" >"${run_dir}/external.csv"
request "/v1/external-runs/${external_id}/artifacts/source/sample.out" >"${run_dir}/raw-import.out"
cmp "${run_dir}/source.out" "${run_dir}/raw-import.out"
request "/v1/external-runs/${external_id}/archive" >"${run_dir}/external.nova-run"
base64 -w0 "${run_dir}/external.nova-run" | jq -Rs '{content_base64:.}' >"${run_dir}/external-import.json"
restored_external_id="$(request /v1/external-runs/import --data-binary @"${run_dir}/external-import.json" | jq -er .id)"
[[ "${restored_external_id}" != "${external_id}" ]]
request "/v1/runs/${restored_external_id}" | jq -e --arg origin "${external_id}" '.imported_from_run==$origin and .external_job.operation=="portable_import" and .result.data.values==[[10],[20]]' >/dev/null
request "/v1/external-runs/${restored_external_id}/artifacts/source/sample.out" >"${run_dir}/restored-source.out"
cmp "${run_dir}/source.out" "${run_dir}/restored-source.out"
mkdir "${run_dir}/input-case"
printf 'NOVA fixture input\n' >"${run_dir}/input-case/main.fst"
cat >"${run_dir}/openfast-fixture" <<'PROGRAM'
#!/bin/sh
if [ "$1" = '-v' ]; then
  echo 'OpenFAST-v4.1.1'
  exit 0
fi
test "$1" = 'case/main.fst' || exit 7
cat >case/main.out <<'DATA'
NOVA original integration fixture
Time GenPwr
(s) (kW)
0 10
1 20
DATA
PROGRAM
chmod 755 "${run_dir}/openfast-fixture"
jq -n --arg executable "${run_dir}/openfast-fixture" '{executable:$executable,environment_kind:"local_executable"}' >"${run_dir}/integration.json"
integration_id="$(request /v1/adapters/openfast/configure --data-binary @"${run_dir}/integration.json" | jq -er .id)"
jq -n --arg id "${integration_id}" --arg directory "${run_dir}/input-case" '{integration_id:$id,case:{case_directory:$directory,input_file:"main.fst",output_file:"main.out",timeout_seconds:10}}' >"${run_dir}/external-case.json"
jq '{case:.case}' "${run_dir}/external-case.json" >"${run_dir}/case-inspect.json"
request /v1/openfast/inspect --data-binary @"${run_dir}/case-inspect.json" | jq -e '.file_count==1 and .input_files[0].path=="main.fst"' >/dev/null
external_id="$(request /v1/external-runs --data-binary @"${run_dir}/external-case.json" | jq -er .id)"
for _ in {1..30}; do
  request "/v1/runs/${external_id}" >"${run_dir}/external-result.json"
  state="$(jq -r .state "${run_dir}/external-result.json")"
  case "${state}" in
    succeeded) break ;;
    failed|cancelled|interrupted) cat "${run_dir}/external-result.json" >&2; exit 1 ;;
  esac
  sleep 1
done
jq -e '.state == "succeeded" and .result.data.values == [[10],[20]]' "${run_dir}/external-result.json" >/dev/null
echo 'Installed OpenFAST import, portable result archive and external execution fixture passed without system Python.'
echo 'Installed native workflow, shared geometry/revision/history, two-axis study, frozen comparison, STL and archive import passed.'
