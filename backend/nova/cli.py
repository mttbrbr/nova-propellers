"""Headless workflow validation/execution: python -m nova.cli."""
import argparse
import json
from pathlib import Path

from nova.workflow.engine import execute, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('validate', 'run', 'study', 'import-openfast'))
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    if args.operation == 'import-openfast':
        from nova.adapters.openfast import read_openfast_output
        print(json.dumps(read_openfast_output(args.project), indent=2, allow_nan=False))
        return
    document = json.loads(args.project.read_text())
    if args.operation == 'validate':
        result = validate(document.get('workflow', document))
    elif args.operation == 'study':
        from nova.application.studies import execute_study
        result = execute_study(document, document['study'])
    else:
        result = execute(document['workflow'], document['inputs'], document.get('polar_asset'), document.get('conditions'),
                         external_context=document.get('external_job'))
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.operation == 'study' and result['study_status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
