"""Nova DISCON controller for OpenFAST: build the shared library and write its ServoDyn and parameter files.

The library (``discon/nova_discon.c``) is compiled once with the system C compiler into Nova's data folder,
keyed by the source hash; OpenFAST loads it through ServoDyn's Bladed interface. The controller has the
semantics of Nova's control blocks (kω² torque law with a rated-torque cap; PI/PID pitch on rotor speed
with output limits, anti-windup and an optional gain schedule), so a native simulation and an OpenFAST run
use the same controller.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np

SOURCE = Path(__file__).with_name('discon') / 'nova_discon.c'
LIBRARY = 'nova_discon.so'
PARAMETERS = 'nova_discon.in'


class DisconError(RuntimeError):
    pass


def build(cache_dir):
    """Compiled library path (built on first use with cc/gcc, then reused while the source is unchanged)."""
    source = SOURCE.read_bytes()
    digest = hashlib.sha256(source).hexdigest()[:16]
    target = Path(cache_dir) / f'nova_discon-{digest}.so'
    if target.exists():
        return target
    compiler = shutil.which('cc') or shutil.which('gcc')
    if not compiler:
        raise DisconError('Building the Nova DISCON controller needs a C compiler (cc or gcc)')
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix('.tmp.so')
    result = subprocess.run([compiler, '-O2', '-shared', '-fPIC', '-o', str(scratch), str(SOURCE), '-lm'], capture_output=True, text=True,
                            timeout=120)
    if result.returncode:
        raise DisconError(f'Compiling the Nova DISCON controller failed: {result.stderr[-2000:]}')
    scratch.replace(target)
    return target


def parameters(controller):
    """Parameter file from a controller description (Nova units: rotor speed rad/s, pitch deg, torque N·m)."""
    pitch = controller.get('pitch') or {}
    lines = ['# Nova DISCON parameters (written by Nova)',
             f"torque_k {float(controller['torque_k_nms2']):.10g}",
             f"rated_torque {float(controller.get('rated_torque_nm') or 1e30):.10g}",
             f"gearbox_ratio {float(controller.get('gearbox_ratio', 1.0)):.10g}",
             f"pitch_enabled {1 if pitch else 0}"]
    if pitch:
        lines += [f"kp {float(pitch['kp']):.10g}", f"ki {float(pitch.get('ki', 0.0)):.10g}", f"setpoint {float(pitch['setpoint']):.10g}",
                  f"pitch_min {float(pitch.get('min', 0.0)):.10g}", f"pitch_max {float(pitch.get('max', 90.0)):.10g}",
                  f"offset {float(pitch.get('offset', 0.0)):.10g}", f"reverse {1 if pitch.get('reverse', True) else 0}"]
        for x, y in zip(pitch.get('schedule_breakpoints') or [], pitch.get('schedule_values') or []):
            lines.append(f'schedule_point {float(x):.10g} {float(y):.10g}')
    return '\n'.join(lines) + '\n'


def servodyn(controller, *, title='Nova controller through the Bladed interface'):
    efficiency = float(controller.get('generator_efficiency', 1.0)) * 100
    return f"""------- SERVODYN v1.05.* INPUT FILE --------------------------------------------
{title}
---------------------- SIMULATION CONTROL --------------------------------------
False         Echo         - Echo input data to <RootName>.ech (flag)
"default"     DT           - Communication interval for controllers (s) (or "default")
---------------------- PITCH CONTROL -------------------------------------------
          5   PCMode       - Pitch control mode {{0: none, 3: user-defined from routine PitchCntrl, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
          0   TPCOn        - Time to enable active pitch control (s) [unused when PCMode=0]
          0   PitNeut(1)   - Blade 1 neutral pitch position--pitch spring moment is zero at this pitch (degrees)
          0   PitNeut(2)   - Blade 2 neutral pitch position--pitch spring moment is zero at this pitch (degrees)
          0   PitNeut(3)   - Blade 3 neutral pitch position--pitch spring moment is zero at this pitch (degrees)
          0   PitSpr(1)    - Blade 1 pitch spring constant (N-m/rad)
          0   PitSpr(2)    - Blade 2 pitch spring constant (N-m/rad)
          0   PitSpr(3)    - Blade 3 pitch spring constant (N-m/rad)
          0   PitDamp(1)   - Blade 1 pitch damping constant (N-m/(rad/s))
          0   PitDamp(2)   - Blade 2 pitch damping constant (N-m/(rad/s))
          0   PitDamp(3)   - Blade 3 pitch damping constant (N-m/(rad/s))
     9999.9   TPitManS(1)  - Time to start override pitch maneuver for blade 1 and end standard pitch control (s)
     9999.9   TPitManS(2)  - Time to start override pitch maneuver for blade 2 and end standard pitch control (s)
     9999.9   TPitManS(3)  - Time to start override pitch maneuver for blade 3 and end standard pitch control (s) [unused for 2 blades]
          2   PitManRat(1) - Pitch rate at which override pitch maneuver heads toward final pitch angle for blade 1 (deg/s)
          2   PitManRat(2) - Pitch rate at which override pitch maneuver heads toward final pitch angle for blade 2 (deg/s)
          2   PitManRat(3) - Pitch rate at which override pitch maneuver heads toward final pitch angle for blade 3 (deg/s) [unused for 2 blades]
          0   BlPitchF(1)  - Blade 1 final pitch for pitch maneuvers (degrees)
          0   BlPitchF(2)  - Blade 2 final pitch for pitch maneuvers (degrees)
          0   BlPitchF(3)  - Blade 3 final pitch for pitch maneuvers (degrees) [unused for 2 blades]
---------------------- GENERATOR AND TORQUE CONTROL ----------------------------
          5   VSContrl     - Variable-speed control mode {{0: none, 1: simple VS, 3: user-defined from routine UserVSCont, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
          1   GenModel     - Generator model {{1: simple, 2: Thevenin, 3: user-defined from routine UserGen}} (switch) [used only when VSContrl=0]
{efficiency:.6g}   GenEff       - Generator efficiency [ignored by the Thevenin and user-defined generator models] (%)
True          GenTiStr     - Method to start the generator {{T: timed using TimGenOn, F: generator speed using SpdGenOn}} (flag)
True          GenTiStp     - Method to stop the generator {{T: timed using TimGenOf, F: when generator power = 0}} (flag)
     9999.9   SpdGenOn     - Generator speed to turn on the generator for a startup (HSS speed) (rpm) [used only when GenTiStr=False]
          0   TimGenOn     - Time to turn on the generator for a startup (s) [used only when GenTiStr=True]
     9999.9   TimGenOf     - Time to turn off the generator (s) [used only when GenTiStp=True]
---------------------- SIMPLE VARIABLE-SPEED TORQUE CONTROL --------------------
     9999.9   VS_RtGnSp    - Rated generator speed for simple variable-speed generator control (HSS side) (rpm) [used only when VSContrl=1]
     9999.9   VS_RtTq      - Rated generator torque/constant generator torque in Region 3 for simple variable-speed generator control (HSS side) (N-m) [used only when VSContrl=1]
     9999.9   VS_Rgn2K     - Generator torque constant in Region 2 for simple variable-speed generator control (HSS side) (N-m/rpm^2) [used only when VSContrl=1]
     9999.9   VS_SlPc      - Rated generator slip percentage in Region 2 1/2 for simple variable-speed generator control (%) [used only when VSContrl=1]
---------------------- SIMPLE INDUCTION GENERATOR ------------------------------
     9999.9   SIG_SlPc     - Rated generator slip percentage (%) [used only when VSContrl=0 and GenModel=1]
     9999.9   SIG_SySp     - Synchronous (zero-torque) generator speed (rpm) [used only when VSContrl=0 and GenModel=1]
     9999.9   SIG_RtTq     - Rated torque (N-m) [used only when VSContrl=0 and GenModel=1]
     9999.9   SIG_PORt     - Pull-out ratio (Tpullout/Trated) (-) [used only when VSContrl=0 and GenModel=1]
---------------------- THEVENIN-EQUIVALENT INDUCTION GENERATOR -----------------
     9999.9   TEC_Freq     - Line frequency [50 or 60] (Hz) [used only when VSContrl=0 and GenModel=2]
       9998   TEC_NPol     - Number of poles [even integer > 0] (-) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_SRes     - Stator resistance (ohms) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_RRes     - Rotor resistance (ohms) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_VLL      - Line-to-line RMS voltage (volts) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_SLR      - Stator leakage reactance (ohms) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_RLR      - Rotor leakage reactance (ohms) [used only when VSContrl=0 and GenModel=2]
     9999.9   TEC_MR       - Magnetizing reactance (ohms) [used only when VSContrl=0 and GenModel=2]
---------------------- HIGH-SPEED SHAFT BRAKE ----------------------------------
          0   HSSBrMode    - HSS brake model {{0: none, 1: simple, 3: user-defined from routine UserHSSBr, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
     9999.9   THSSBrDp     - Time to initiate deployment of the HSS brake (s)
        0.6   HSSBrDT      - Time for HSS-brake to reach full deployment once initiated (sec) [used only when HSSBrMode=1]
          0   HSSBrTqF     - Fully deployed HSS-brake torque (N-m)
---------------------- NACELLE-YAW CONTROL -------------------------------------
          0   YCMode       - Yaw control mode {{0: none, 3: user-defined from routine UserYawCont, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
     9999.9   TYCOn        - Time to enable active yaw control (s) [unused when YCMode=0]
          0   YawNeut      - Neutral yaw position--yaw spring force is zero at this yaw (degrees)
          0   YawSpr       - Nacelle-yaw spring constant (N-m/rad)
          0   YawDamp      - Nacelle-yaw damping constant (N-m/(rad/s))
     9999.9   TYawManS     - Time to start override yaw maneuver and end standard yaw control (s)
          2   YawManRat    - Yaw maneuver rate (in absolute value) (deg/s)
          0   NacYawF      - Final yaw angle for override yaw maneuvers (degrees)
---------------------- AERODYNAMIC FLOW CONTROL --------------------------------
          0   AfCmode      - Airfoil control mode {{0: none, 1: cosine wave cycle, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
          0   AfC_Mean     - Mean level for cosine cycling or steady value (-) [used only with AfCmode==1]
          0   AfC_Amp      - Amplitude for for cosine cycling of flap signal (-) [used only with AfCmode==1]
          0   AfC_Phase    - Phase relative to the blade azimuth (0 is vertical) for for cosine cycling of flap signal (deg) [used only with AfCmode==1]
---------------------- STRUCTURAL CONTROL --------------------------------------
0             NumBStC      - Number of blade structural controllers (integer)
"unused"      BStCfiles    - Name of the files for blade structural controllers (quoted strings) [unused when NumBStC==0]
0             NumNStC      - Number of nacelle structural controllers (integer)
"unused"      NStCfiles    - Name of the files for nacelle structural controllers (quoted strings) [unused when NumNStC==0]
0             NumTStC      - Number of tower structural controllers (integer)
"unused"      TStCfiles    - Name of the files for tower structural controllers (quoted strings) [unused when NumTStC==0]
0             NumSStC      - Number of substructure structural controllers (integer)
"unused"      SStCfiles    - Name of the files for substructure structural controllers (quoted strings) [unused when NumSStC==0]
---------------------- CABLE CONTROL -------------------------------------------
          0   CCmode       - Cable control mode {{0: none, 4: user-defined from Simulink/Labview, 5: user-defined from Bladed-style DLL}} (switch)
---------------------- BLADED INTERFACE ---------------------------------------- [used only with Bladed Interface]
"{LIBRARY}"    DLL_FileName - Name/location of the dynamic library {{.dll [Windows] or .so [Linux]}} in the Bladed-DLL format (-) [used only with Bladed Interface]
"{PARAMETERS}"    DLL_InFile   - Name of input file sent to the DLL (-) [used only with Bladed Interface]
"DISCON"      DLL_ProcName - Name of procedure in DLL to be called (-) [case sensitive; used only with DLL Interface]
"default"     DLL_DT       - Communication interval for dynamic library (s) (or "default") [used only with Bladed Interface]
false         DLL_Ramp     - Whether a linear ramp should be used between DLL_DT time steps [introduces time shift when true] (flag) [used only with Bladed Interface]
     9999.9   BPCutoff     - Cutoff frequency for low-pass filter on blade pitch from DLL (Hz) [used only with Bladed Interface]
          0   NacYaw_North - Reference yaw angle of the nacelle when the upwind end points due North (deg) [used only with Bladed Interface]
          0   Ptch_Cntrl   - Record 28: Use individual pitch control {{0: collective pitch; 1: individual pitch control}} (switch) [used only with Bladed Interface]
          0   Ptch_SetPnt  - Record  5: Below-rated pitch angle set-point (deg) [used only with Bladed Interface]
          0   Ptch_Min     - Record  6: Minimum pitch angle (deg) [used only with Bladed Interface]
         90   Ptch_Max     - Record  7: Maximum pitch angle (deg) [used only with Bladed Interface]
       -100   PtchRate_Min - Record  8: Minimum pitch rate (most negative value allowed) (deg/s) [used only with Bladed Interface]
        100   PtchRate_Max - Record  9: Maximum pitch rate  (deg/s) [used only with Bladed Interface]
          0   Gain_OM      - Record 16: Optimal mode gain (Nm/(rad/s)^2) [used only with Bladed Interface]
          0   GenSpd_MinOM - Record 17: Minimum generator speed (rpm) [used only with Bladed Interface]
          0   GenSpd_MaxOM - Record 18: Optimal mode maximum speed (rpm) [used only with Bladed Interface]
          0   GenSpd_Dem   - Record 19: Demanded generator speed above rated (rpm) [used only with Bladed Interface]
          0   GenTrq_Dem   - Record 22: Demanded generator torque above rated (Nm) [used only with Bladed Interface]
          0   GenPwr_Dem   - Record 13: Demanded power (W) [used only with Bladed Interface]
---------------------- BLADED INTERFACE TORQUE-SPEED LOOK-UP TABLE -------------
          0   DLL_NumTrq   - Record 26: No. of points in torque-speed look-up table {{0 = none and use the optimal mode parameters; nonzero = ignore the optimal mode PARAMETERs by setting Record 16 to 0.0}} (-) [used only with Bladed Interface]
 GenSpd_TLU   GenTrq_TLU
 (rpm)          (Nm)
---------------------- OUTPUT --------------------------------------------------
False         SumPrint     - Print summary data to <RootName>.sum (flag) (currently unused)
          1   OutFile      - Switch to determine where output will be placed: {{1: in module output file only; 2: in glue code output file only; 3: both}} (currently unused)
True          TabDelim     - Use tab delimiters in text tabular output file? (flag) (currently unused)
"ES10.3E2"    OutFmt       - Format used for text tabular output (except time).  Resulting field should be 10 characters. (quoted string) (currently unused)
          0   TStart       - Time to begin tabular output (s) (currently unused)
              OutList      - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
"GenPwr"
"GenTq"
END of input file (the word "END" must appear in the first 3 columns of this last OutList line)
---------------------------------------------------------------------------------------
"""


def uniform_wind(times, speeds, shear_exponent=0.0):
    """InflowWind uniform wind file: time, horizontal speed, direction, vertical speed, shears and gust."""
    lines = ['! Nova uniform wind (written by Nova)',
             '! Time  Wind  WindDir  VertSpd  HorizShr  VertShr  LinVShr  GustSpd',
             '! (s)   (m/s) (deg)    (m/s)    (-)       (-)      (-)      (m/s)']
    for t, v in zip(times, speeds):
        lines.append(f'{float(t):.6f} {float(v):.6f} 0 0 0 {float(shear_exponent):.6f} 0 0')
    return '\n'.join(lines) + '\n'


def from_chain(elements, duration_s, step_s=0.1):
    """Controller description for OpenFAST from a chain of control elements (Nova control blocks).

    Supported: one kω² torque law, one PI/PID pitch controller on the rotor speed (its gain schedule from a lookup
    element, if any), the wind source (sampled into a uniform wind file) and the aeroelastic turbine's gearbox,
    generator inertia and efficiency. Anything else has no OpenFAST counterpart and is refused."""
    from nova.physics import control
    plant = next((e for e in elements if e.get('element') == 'aeroelastic_turbine'), None)
    names = {k: (plant or {}).get(k, default) for k, default in (('wind', 'wind_speed'), ('generator_torque', 'gen_torque'),
                                                                ('pitch', 'pitch'), ('speed', 'rotor_speed'))}
    torque = [e for e in elements if e.get('element') == 'torque_law' and e.get('output') == names['generator_torque']]
    pitch = [e for e in elements if e.get('element') == 'pid' and e.get('output') == names['pitch']]
    wind = [e for e in elements if e.get('element') == 'source' and e.get('output') == names['wind']]
    if len(torque) != 1:
        raise DisconError(f"OpenFAST needs exactly one kω² torque law writing {names['generator_torque']}")
    used = {id(torque[0]), *(id(e) for e in pitch), *(id(e) for e in wind), *([id(plant)] if plant else [])}
    controller = {'torque_k_nms2': float(torque[0]['k']), 'rated_torque_nm': torque[0].get('rated_torque_nm'),
                  'gearbox_ratio': float((plant or {}).get('gearbox_ratio', 1.0)),
                  'generator_inertia_kg_m2': float((plant or {}).get('generator_inertia_kg_m2', 0.0)),
                  'generator_efficiency': float((plant or {}).get('generator_efficiency', 1.0))}
    if torque[0].get('input', names['speed']) != names['speed']:
        raise DisconError('The torque law must read the rotor speed')
    if len(pitch) > 1:
        raise DisconError('OpenFAST takes one collective pitch controller')
    if pitch:
        pid = pitch[0]
        if pid.get('measurement') != names['speed'] or not isinstance(pid.get('setpoint'), (int, float)):
            raise DisconError('The pitch controller must regulate the rotor speed to a numeric set point')
        if pid.get('kd'):
            raise DisconError('The OpenFAST controller supports PI pitch control (kd must be 0)')
        controller['pitch'] = {'kp': pid.get('kp', 0.0), 'ki': pid.get('ki', 0.0), 'setpoint': pid['setpoint'], 'min': pid.get('min', 0.0),
                               'max': pid.get('max', 90.0), 'offset': pid.get('offset', 0.0), 'reverse': pid.get('reverse', False)}
        if pid.get('gain_signal'):
            table = [e for e in elements if e.get('element') == 'lookup' and e.get('output') == pid['gain_signal']]
            if len(table) != 1 or table[0].get('input') != names['pitch']:
                raise DisconError('The pitch gain schedule must be a lookup on the pitch angle')
            used.add(id(table[0]))
            controller['pitch'].update(schedule_breakpoints=table[0]['breakpoints'], schedule_values=table[0]['values'])
    if len(wind) == 1:
        source = control.Source(wind[0])
        signals = {}
        times = np.arange(0.0, duration_s + step_s / 2, step_s)
        speeds = []
        for t in times:
            source.step(float(t), signals, step_s)
            speeds.append(signals[names['wind']])
        controller['wind'] = {'times': times.tolist(), 'speeds': speeds}
    elif wind:
        raise DisconError('Give one wind source')
    extra = [e.get('element') for e in elements if id(e) not in used]
    if extra:
        raise DisconError(f"No OpenFAST counterpart for: {', '.join(sorted(set(extra)))}")
    return controller
