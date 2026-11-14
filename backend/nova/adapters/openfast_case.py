"""Write an OpenFAST 5.0 input case from a Nova rotor.

Rigid-rotor aerodynamics: Simplified ElastoDyn (CompElast=3) with prescribed rotor speed and pitch,
AeroDyn (quasi-steady BEMT), steady InflowWind. No structure, controller or tower is modelled, so
nothing here is invented: every number comes from the Nova rotor, its operating point or the
explicit settings below. Airfoil tables are Nova's own polars evaluated at each station's Reynolds
number, so both codes see the same section data.

File layouts follow the module input files of OpenFAST v5.0.0 (sequential `value  Key  - text`).
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from nova.adapters import openfast_structure
from nova.physics import beam_modes, rotors
from nova.physics.sections import GRID_DEG

ROOT = 'rigid'
OUTPUT = f'{ROOT}.outb'
FLEX = 'flex'
ED_NODES = 20
ED_BLADE = 'flex_ElastoDyn_blade.dat'
ED_TOWER = 'flex_ElastoDyn_tower.dat'
DOF_SETTINGS = {'flap_dof': True, 'edge_dof': True, 'tower_fa_dof': True, 'tower_ss_dof': True}
SETTINGS = {'duration_s': 10.0, 'dt_s': 0.01, 'hub_height_m': None, 'overhang_m': None, 'shaft_tilt_deg': 0.0, 'precone_deg': 0.0}
LIMITS = {'duration_s': (0.1, 600.0), 'dt_s': (1e-4, 0.5), 'hub_height_m': (0.1, 1000.0), 'overhang_m': (-100.0, 100.0),
          'shaft_tilt_deg': (-30.0, 30.0), 'precone_deg': (-30.0, 30.0)}
AERO_OUTPUTS = ('RtAeroPwr', 'RtAeroCp', 'RtAeroCt', 'RtAeroFxh', 'RtAeroMxh', 'RtSpeed', 'RtTSR', 'RtVAvgxh')
SED_OUTPUTS = ('RotSpeed', 'Azimuth')


class CaseError(ValueError):
    pass


def _settings(given):
    unknown = set(given or {}) - set(SETTINGS) - set(DOF_SETTINGS)
    if unknown:
        raise CaseError(f'Unsupported OpenFAST case settings: {", ".join(sorted(unknown))}')
    merged = {**SETTINGS, **DOF_SETTINGS, **{k: v for k, v in (given or {}).items() if v is not None}}
    for key in DOF_SETTINGS:
        if not isinstance(merged[key], bool):
            raise CaseError(f'{key} must be true or false')
    for key, value in merged.items():
        if value is None or key in DOF_SETTINGS:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CaseError(f'{key} must be a finite number')
        low, high = LIMITS[key]
        if not low <= value <= high:
            raise CaseError(f'{key} must be between {low:g} and {high:g}')
    if merged['dt_s'] > merged['duration_s']:
        raise CaseError('dt_s cannot exceed duration_s')
    if merged['duration_s'] / merged['dt_s'] > 2_000_000:
        raise CaseError('The run would need more than two million time steps')
    return merged


def _num(value):
    return f'{float(value):.10g}'


def _fst(settings):
    title = ('Nova flexible rotor: ElastoDyn with prescribed rotor speed, AeroDyn BEMT, steady wind.' if settings['_elast'] == 1
             else 'Nova rigid rotor: Simplified ElastoDyn with prescribed speed and pitch, AeroDyn BEMT, steady wind.')
    return f"""------- OpenFAST INPUT FILE (written by Nova) ----------------------
{title}
---------------------- SIMULATION CONTROL --------------------------------------
False          Echo            - Echo input data to <RootName>.ech (flag)
"FATAL"        AbortLevel      - Error level when simulation should abort (string) {{"WARNING", "SEVERE", "FATAL"}}
{_num(settings['duration_s'])}   TMax            - Total run time (s)
{_num(settings['dt_s'])}   DT              - Recommended module time step (s)
          1   ModCoupling     - Module coupling method (switch) {{1=loose; 2=tight with fixed Jacobian updates (DT_UJac); 3=tight with automatic Jacobian updates}}
          1   InterpOrder     - Interpolation order for input/output time history (-) {{1=linear, 2=quadratic}}
          0   NumCrctn        - Number of correction iterations (-) {{0=explicit calculation, i.e., no corrections}}
        0.0   RhoInf          - Numerical damping parameter for tight coupling generalized-alpha integrator (-) [0.0 to 1.0]
       1e-4   ConvTol         - Convergence iteration error tolerance for tight coupling generalized alpha integrator (-)
          6   MaxConvIter     - Maximum number of convergence iterations for tight coupling generalized alpha integrator (-)
      99999   DT_UJac         - Time between calls to get Jacobians (s)
    1000000   UJacSclFact     - Scaling factor used in Jacobians (-)
---------------------- FEATURE SWITCHES AND FLAGS ------------------------------
          1   NRotors         - Number of rotors in turbine (-)
{settings['_elast']}   CompElast       - Compute structural dynamics (switch) {{1=ElastoDyn; 2=ElastoDyn + BeamDyn for blades; 3=Simplified ElastoDyn}}
          1   CompInflow      - Compute inflow wind velocities (switch) {{0=still air; 1=InflowWind; 2=external from ExtInflow}}
          2   CompAero        - Compute aerodynamic loads (switch) {{0=None; 1=AeroDisk; 2=AeroDyn; 3=ExtLoads}}
          0   CompServo       - Compute control and electrical-drive dynamics (switch) {{0=None; 1=ServoDyn}}
          0   CompSeaSt       - Compute sea state information (switch) {{0=None; 1=SeaState}}
          0   CompHydro       - Compute hydrodynamic loads (switch) {{0=None; 1=HydroDyn}}
          0   CompSub         - Compute sub-structural dynamics (switch) {{0=None; 1=SubDyn; 2=External Platform MCKF}}
          0   CompMooring     - Compute mooring system (switch) {{0=None; 1=MAP++; 2=FEAMooring; 3=MoorDyn; 4=OrcaFlex}}
          0   CompIce         - Compute ice loads (switch) {{0=None; 1=IceFloe; 2=IceDyn}}
          0   CompSoil        - Compute soil-structural dynamics (switch) {{0=None; 1=SoilDyn}}
          0   MHK             - MHK turbine type (switch) {{0=Not an MHK turbine; 1=Fixed MHK turbine; 2=Floating MHK turbine}}
          F   MirrorRotor     - Flag to reverse rotor rotation direction [1 to NRotors] {{F=Normal, T=Mirror}}
---------------------- ENVIRONMENTAL CONDITIONS --------------------------------
    9.80665   Gravity         - Gravitational acceleration (m/s^2)
{settings['_rho']}   AirDens         - Air density (kg/m^3)
          0   WtrDens         - Water density (kg/m^3)
{settings['_nu']}   KinVisc         - Kinematic viscosity of working fluid (m^2/s)
{settings['_a']}   SpdSound        - Speed of sound in working fluid (m/s)
{settings['_p']}   Patm            - Atmospheric pressure (Pa) [used only for an MHK turbine cavitation check]
       1700   Pvap            - Vapour pressure of working fluid (Pa) [used only for an MHK turbine cavitation check]
          0   WtrDpth         - Water depth (m)
          0   MSL2SWL         - Offset between still-water level and mean sea level (m) [positive upward]
---------------------- INPUT FILES ---------------------------------------------
"{settings['_edfile']}"    EDFile          - Name of file containing ElastoDyn/Simplified-ElastoDyn input parameters (quoted string)
"unused"      BDBldFile(1)    - Name of file containing BeamDyn input parameters for blade 1 (quoted string)
"unused"      BDBldFile(2)    - Name of file containing BeamDyn input parameters for blade 2 (quoted string)
"unused"      BDBldFile(3)    - Name of file containing BeamDyn input parameters for blade 3 (quoted string)
"{settings['_root']}_InflowWind.dat"    InflowFile      - Name of file containing inflow wind input parameters (quoted string)
"{settings['_root']}_AeroDyn.dat"     AeroFile        - Name of file containing aerodynamic input parameters (quoted string)
"unused"      ServoFile       - Name of file containing control and electrical-drive input parameters (quoted string)
"unused"      SeaStFile       - Name of file containing sea state input parameters (quoted string)
"unused"      HydroFile       - Name of file containing hydrodynamic input parameters (quoted string)
"unused"      SubFile         - Name of file containing sub-structural input parameters (quoted string)
"unused"      MooringFile     - Name of file containing mooring system input parameters (quoted string)
"unused"      IceFile         - Name of file containing ice input parameters (quoted string)
"unused"      SoilFile        - Name of the file containing the SoilDyn input parameters (quoted string)
---------------------- OUTPUT --------------------------------------------------
False         SumPrint        - Print summary data to "<RootName>.sum" (flag)
          5   SttsTime        - Amount of time between screen status messages (s)
      99999   ChkptTime       - Amount of time between creating checkpoint files for potential restart (s)
"default"     DT_Out          - Time step for tabular output (s) (or "default")
          0   TStart          - Time to begin tabular output (s)
          0   OutFileFmt      - Format for tabular (time-marching) output file (switch) {{0: uncompressed binary [<RootName>.outb], 1: text file [<RootName>.out], 2: compressed binary [<RootName>.outb]}}
True          TabDelim        - Use tab delimiters in text tabular output file? (flag) {{uses spaces if false}}
"ES10.3E2"    OutFmt          - Format used for text tabular output, excluding the time channel.  Resulting field should be 10 characters. (quoted string)
---------------------- LINEARIZATION -------------------------------------------
False         Linearize       - Linearization analysis (flag)
False         CalcSteady      - Calculate a steady-state periodic operating point before linearization? [unused if Linearize=False] (flag)
          3   TrimCase        - Controller parameter to be trimmed {{1:yaw; 2:torque; 3:pitch}} [used only if CalcSteady=True] (-)
      0.001   TrimTol         - Tolerance for the rotational speed convergence [used only if CalcSteady=True] (-)
       0.01   TrimGain        - Proportional gain for the rotational speed error (>0) [used only if CalcSteady=True] (rad/(rad/s) for yaw or generator torque, rad/(rad/s) for pitch)
          0   Twr_Kdmp        - Damping factor for the tower [used only if CalcSteady=True] (N/(m/s))
          0   Bld_Kdmp        - Damping factor for the blades [used only if CalcSteady=True] (N/(m/s))
          2   NLinTimes       - Number of times to linearize (-) [>=1] [unused if Linearize=False]
         30,         60    LinTimes        - List of times at which to linearize (s) [1 to NLinTimes] [used only when Linearize=True and CalcSteady=False]
          1   LinInputs       - Inputs included in linearization (switch) {{0=none; 1=standard; 2=all module inputs (debug)}} [unused if Linearize=False]
          1   LinOutputs      - Outputs included in linearization (switch) {{0=none; 1=from OutList(s); 2=all module outputs (debug)}} [unused if Linearize=False]
False         LinOutJac       - Include full Jacobians in linearization (for debug) (flag) [unused if Linearize=False; used only if LinInputs=LinOutputs=2]
False         LinOutMod       - Write module-level linearization output files in addition to output for full system? (flag) [unused if Linearize=False]
---------------------- VISUALIZATION ------------------------------------------
          0   WrVTK           - VTK visualization data output: (switch) {{0=none; 1=initialization data only; 2=animation; 3=mode shapes}}
          1   VTK_type        - Type of VTK visualization data: (switch) {{1=surfaces; 2=basic meshes (lines/points); 3=all meshes (debug)}} [unused if WrVTK=0]
true          VTK_fields      - Write mesh fields to VTK data files? (flag) {{true/false}} [unused if WrVTK=0]
          0   VTK_fps         - Frame rate for VTK output (frames per second){{will use closest integer multiple of DT}} [used only if WrVTK=2 or WrVTK=3]
"""


def _sed(blades, tip_radius, hub_radius, rpm, pitch_deg, settings):
    outputs = ''.join(f'"{name}"\n' for name in SED_OUTPUTS)
    return f"""------- SIMPLIFIED ELASTODYN INPUT FILE ----------------------------------------
Nova rigid rotor: prescribed rotor speed and pitch, no degrees of freedom.
---------------------- SIMULATION CONTROL --------------------------------------
False         Echo        - Echo input data to "<RootName>.ech" (flag)
          3   IntMethod   - Integration method: {{1: RK4, 2: AB4, or 3: ABM4}} (-)
"default"     DT          - Integration time step (s)
---------------------- DEGREES OF FREEDOM --------------------------------------
False         GenDOF      - Generator DOF (flag)
False         YawDOF      - Yaw degree of freedom -- controlled by controller (flag)
---------------------- INITIAL CONDITIONS --------------------------------------
          0   Azimuth     - Initial azimuth angle for blades (degrees)
{_num(pitch_deg)}   BlPitch     - Blades initial pitch (degrees)
{_num(rpm)}   RotSpeed    - Initial or fixed rotor speed (rpm)
          0   NacYaw      - Initial or fixed nacelle-yaw angle (degrees)
          0   PtfmPitch   - Fixed pitch tilt rotational displacement of platform (degrees)
---------------------- TURBINE CONFIGURATION -----------------------------------
{int(blades)}   NumBl       - Number of blades (-)
{_num(tip_radius)}   TipRad      - The distance from the rotor apex to the blade tip (meters)
{_num(hub_radius)}   HubRad      - The distance from the rotor apex to the blade root (meters)
{_num(settings['precone_deg'])}   PreCone     - Blades cone angle (degrees)
{_num(settings['overhang_m'])}   OverHang    - Distance from yaw axis to rotor apex [3 blades] or teeter pin [2 blades] (meters)
{_num(settings['shaft_tilt_deg'])}   ShftTilt    - Rotor shaft tilt angle (degrees)
{_num(settings['_twr2shft'])}   Twr2Shft    - Vertical distance from the tower-top to the rotor shaft (meters)
{_num(settings['_tower_ht'])}   TowerHt     - Height of tower above ground level [onshore] or MSL [offshore] (meters)
---------------------- MASS AND INERTIA ----------------------------------------
1.0E+06   RotIner     - Rot inertia about rotor axis [blades + hub] (kg m^2) (unused with fixed speed)
1.0   GenIner     - Generator inertia about HSS (kg m^2) (unused with fixed speed)
---------------------- DRIVETRAIN ----------------------------------------------
1   GBoxRatio   - Gearbox ratio (-)
---------------------- OUTPUT --------------------------------------------------
              OutList     - The next line(s) contains a list of output parameters.
{outputs}END of input file (the word "END" must appear in the first 3 columns of this last OutList line)
"""


def _inflow(speed, ref_height):
    return f"""------- InflowWind INPUT FILE -------------------------------------------------------------------------
Nova steady uniform wind, no shear.
---------------------------------------------------------------------------------------------------------------
False         Echo           - Echo input data to <RootName>.ech (flag)
          1   WindType       - switch for wind file type (1=steady; 2=uniform; 3=binary TurbSim FF; 4=binary Bladed-style FF; 5=HAWC format; 6=User defined; 7=native Bladed FF)
          0   PropagationDir - Direction of wind propagation (meteorological rotation from aligned with X (positive rotates towards -Y)) (deg)
          0   VFlowAng       - Upflow angle (degrees) (not used for native Bladed format WindType=7)
False         VelInterpCubic - Use cubic interpolation for velocity in time (false=linear, true=cubic) [Used with WindType=2,3,4,5,7]
          1   NWindVel       - Number of points to output the wind velocity    (0 to 9)
          0   WindVxiList    - List of coordinates in the inertial X direction (m)
          0   WindVyiList    - List of coordinates in the inertial Y direction (m)
{_num(ref_height)}   WindVziList    - List of coordinates in the inertial Z direction (m)
================== Parameters for Steady Wind Conditions [used only for WindType = 1] =========================
{_num(speed)}   HWindSpeed     - Horizontal wind speed                           (m/s)
{_num(ref_height)}   RefHt          - Reference height for horizontal wind speed      (m)
          0   PLExp          - Power law exponent                              (-)
================== Parameters for Uniform wind file   [used only for WindType = 2] ============================
"unused"      FileName_Uni   - Filename of time series data for uniform wind field.      (-)
         90   RefHt_Uni      - Reference height for horizontal wind speed                (m)
     125.88   RefLength      - Reference length for linear horizontal and vertical sheer (-)
================== Parameters for Binary TurbSim Full-Field files   [used only for WindType = 3] ==============
"unused"      FileName_BTS   - Name of the Full field wind file to use (.bts)
================== Parameters for Binary Bladed-style Full-Field files   [used only for WindType = 4 or WindType = 7] ==
"unused"      FileNameRoot   - WindType=4: Rootname of the full-field wind file to use (.wnd, .sum); WindType=7: name of the file (.wnd)
False         TowerFile      - Have tower file (.twr) (flag) ignored when WindType = 7
================== Parameters for HAWC-format binary files  [Only used with WindType = 5] =====================
"unused"      FileName_u     - name of the file containing the u-component fluctuating wind (.bin)
"unused"      FileName_v     - name of the file containing the v-component fluctuating wind (.bin)
"unused"      FileName_w     - name of the file containing the w-component fluctuating wind (.bin)
         64   nx             - number of grids in the x direction (in the 3 files above) (-)
         32   ny             - number of grids in the y direction (in the 3 files above) (-)
         32   nz             - number of grids in the z direction (in the 3 files above) (-)
         16   dx             - distance (in meters) between points in the x direction    (m)
          3   dy             - distance (in meters) between points in the y direction    (m)
          3   dz             - distance (in meters) between points in the z direction    (m)
         90   RefHt_Hawc     - reference height; the height (in meters) of the vertical center of the grid (m)
  -------------   Scaling parameters for turbulence   ---------------------------------------------------------
          1   ScaleMethod    - Turbulence scaling method   [0 = none, 1 = direct scaling, 2 = calculate scaling factor based on a desired standard deviation]
          1   SFx            - Turbulence scaling factor for the x direction (-)   [ScaleMethod=1]
          1   SFy            - Turbulence scaling factor for the y direction (-)   [ScaleMethod=1]
          1   SFz            - Turbulence scaling factor for the z direction (-)   [ScaleMethod=1]
         12   SigmaFx        - Turbulence standard deviation to calculate scaling from in x direction (m/s)    [ScaleMethod=2]
          8   SigmaFy        - Turbulence standard deviation to calculate scaling from in y direction (m/s)    [ScaleMethod=2]
          2   SigmaFz        - Turbulence standard deviation to calculate scaling from in z direction (m/s)    [ScaleMethod=2]
  -------------   Mean wind profile parameters (added to HAWC-format files)   ---------------------------------
          5   URef           - Mean u-component wind speed at the reference height (m/s)
          2   WindProfile    - Wind profile type (0=constant;1=logarithmic,2=power law)
          0   PLExp_Hawc     - Power law exponent (-) (used for PL wind profile type only)
       0.03   Z0             - Surface roughness length (m) (used for LG wind profile type only)
          0   XOffset        - Initial offset in +x direction (shift of wind box)
================== LIDAR Parameters ===========================================================================
          0   SensorType          - Switch for lidar configuration (0 = None, 1 = Single Point Beam(s), 2 = Continuous, 3 = Pulsed)
          0   NumPulseGate        - Number of lidar measurement gates (used when SensorType = 3)
         30   PulseSpacing        - Distance between range gates (m) (used when SensorType = 3)
          0   NumBeam             - Number of lidar measurement beams (0-5)(used when SensorType = 1)
       -200   FocalDistanceX      - Focal distance co-ordinates of the lidar beam in the x direction (relative to hub height) (only first coordinate used for SensorType 2 and 3) (m)
          0   FocalDistanceY      - Focal distance co-ordinates of the lidar beam in the y direction (relative to hub height) (only first coordinate used for SensorType 2 and 3) (m)
          0   FocalDistanceZ      - Focal distance co-ordinates of the lidar beam in the z direction (relative to hub height) (only first coordinate used for SensorType 2 and 3) (m)
          0,          0,          0    RotorApexOffsetPos  - Offset of the lidar from hub height (m)
         17   URefLid             - Reference average wind speed for the lidar[m/s]
       0.25   MeasurementInterval - Time between each measurement [s]
False         LidRadialVel        - TRUE => return radial component, FALSE => return 'x' direction estimate
          1   ConsiderHubMotion   - Flag whether to consider the hub motion's impact on Lidar measurements
====================== OUTPUT ==================================================
False         SumPrint     - Print summary data to <RootName>.IfW.sum (flag)
              OutList      - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
"Wind1VelX"               X-direction wind velocity at point WindList(1)
END of input file (the word "END" must appear in the first 3 columns of this last OutList line)
"""


def _aerodyn(count, corrections):
    tip = 'True' if corrections.get('tip_loss', 'prandtl') != 'none' else 'False'
    hub = 'True' if corrections.get('hub_loss', 'prandtl') != 'none' else 'False'
    files = '\n'.join(f'"airfoils/station_{i + 1:02d}.dat"' + (' AFNames - Airfoil file names (NumAFfiles lines) (quoted strings)' if i == 0 else '') for i in range(count))
    outputs = ''.join(f'"{name}"\n' for name in AERO_OUTPUTS)
    return f"""------- AERODYN INPUT FILE --------------------------------------------------------------------------
Nova rigid rotor: quasi-steady BEMT, no tower influence, no unsteady aerodynamics.
======  General Options  ============================================================================
False                  Echo        - Echo the input to "<rootname>.AD.ech"? (flag)
"default"              DTAero      - Time interval for aerodynamic calculations {{or "default"}} (s)
1                      Wake_Mod    - Wake/induction model (switch) {{0=none, 1=BEMT, 3=OLAF}}
0                      TwrPotent   - Type tower influence on wind based on potential flow around the tower (switch) {{0=none, 1=baseline potential flow, 2=potential flow with Bak correction}}
0                      TwrShadow   - Calculate tower influence on wind based on downstream tower shadow (switch) {{0=none, 1=Powles model, 2=Eames model}}
False                  TwrAero     - Calculate tower aerodynamic loads? (flag)
False                  CavitCheck  - Perform cavitation check? (flag) [UA_Mod must be 0 when CavitCheck=true]
False                  NacelleDrag - Include Nacelle Drag effects? (flag)
False                  CompAA      - Flag to compute AeroAcoustics calculation [used only when Wake_Mod = 1 or 2]
"unused"               AA_InputFile - AeroAcoustics input file [used only when CompAA=true]
======  Environmental Conditions  ===================================================================
"default"              AirDens     - Air density (kg/m^3)
"default"              KinVisc     - Kinematic viscosity of working fluid (m^2/s)
"default"              SpdSound    - Speed of sound in working fluid (m/s)
"default"              Patm        - Atmospheric pressure (Pa) [used only when CavitCheck=True]
"default"              Pvap        - Vapour pressure of working fluid (Pa) [used only when CavitCheck=True]
======  Blade-Element/Momentum Theory Options  ======================================================
1                      BEM_Mod     - BEM model {{1=legacy NoSweepPitchTwist, 2=polar}} (switch)
--- Skew correction
0                      Skew_Mod    - Skew model {{0=No skew model, -1=Remove non-normal component for linearization, 1=skew model active}}
False                  SkewMomCorr - Turn the skew momentum correction on or off [used only when Skew_Mod=1]
default                SkewRedistr_Mod - Type of skewed-wake correction model (switch) {{0=no redistribution, 1=Glauert/Pitt/Peters, default=1}} [used only when Skew_Mod=1]
"default"              SkewRedistrFactor - Constant used in Pitt/Peters skewed wake model {{or "default" is 15/32*pi}} (-) [used only when Skew_Mod=1 and SkewRedistr_Mod=1]
--- BEM algorithm
{tip}                   TipLoss     - Use the Prandtl tip-loss model? (flag)
{hub}                   HubLoss     - Use the Prandtl hub-loss model? (flag)
True                   TanInd      - Include tangential induction in BEMT calculations? (flag)
True                   AIDrag      - Include the drag term in the axial-induction calculation? (flag)
True                   TIDrag      - Include the drag term in the tangential-induction calculation? (flag)
"Default"              IndToler    - Convergence tolerance for BEMT nonlinear solve residual equation {{or "default"}} (-)
100                    MaxIter     - Maximum number of iteration steps (-)
--- Shear correction
False                  SectAvg     - Use sector averaging (flag)
1                      SectAvgWeighting - Weighting function for sector average {{1=Uniform, default=1}} within a sector centered on the blade (switch) [used only when SectAvg=True]
default                SectAvgNPoints - Number of points per sectors (-) {{default=5}} [used only when SectAvg=True]
default                SectAvgPsiBwd - Backward azimuth relative to blade where the sector starts (<=0) {{default=-60}} (deg) [used only when SectAvg=True]
default                SectAvgPsiFwd - Forward azimuth relative to blade where the sector ends (>=0) {{default=60}} (deg) [used only when SectAvg=True]
--- Dynamic wake/inflow
0                      DBEMT_Mod   - Type of dynamic BEMT (DBEMT) model {{0=No Dynamic Wake, -1=Frozen Wake for linearization, 1:constant tau1, 2=time-dependent tau1, 3=constant tau1 with continuous formulation}} (-)
4                      tau1_const  - Time constant for DBEMT (s) [used only when DBEMT_Mod=1 or 3]
======  OLAF -- cOnvecting LAgrangian Filaments (Free Vortex Wake) Theory Options  ==================
"unused"               OLAFInputFileName - Input file for OLAF [used only when Wake_Mod=3]
======  Unsteady Airfoil Aerodynamics Options  ====================================================
True                   AoA34       - Sample the angle of attack (AoA) at the 3/4 chord or the AC point {{default=True}} [always used]
0                      UA_Mod      - Unsteady Aero Model Switch (switch) {{0=Quasi-steady (no UA), 2=B-L Gonzalez, 3=B-L Minnema/Pierce, 4=B-L HGM 4-states, 5=B-L HGM+vortex 5 states, 6=Oye, 7=Boeing-Vertol}}
True                   FLookup     - Flag to indicate whether a lookup for f' will be calculated (TRUE) or whether best-fit exponential equations will be used (FALSE); if FALSE S1-S4 must be provided in airfoil input files (flag)
3               IntegrationMethod  - Switch to indicate which integration method UA uses (1=RK4, 2=AB4, 3=ABM4, 4=BDF2)
0                      UAStartRad  - Starting radius for dynamic stall (fraction of rotor radius [0.0,1.0]) [used only when UA_Mod>0; if line is missing UAStartRad=0]
1                      UAEndRad    - Ending radius for dynamic stall (fraction of rotor radius [0.0,1.0]) [used only when UA_Mod>0; if line is missing UAEndRad=1]
======  Airfoil Information =========================================================================
1                      AFTabMod    - Interpolation method for multiple airfoil tables {{1=1D interpolation on AoA (first table only); 2=2D interpolation on AoA and Re; 3=2D interpolation on AoA and UserProp}} (-)
1                      InCol_Alfa  - The column in the airfoil tables that contains the angle of attack (-)
2                      InCol_Cl    - The column in the airfoil tables that contains the lift coefficient (-)
3                      InCol_Cd    - The column in the airfoil tables that contains the drag coefficient (-)
0                      InCol_Cm    - The column in the airfoil tables that contains the pitching-moment coefficient; use zero if there is no Cm column (-)
0                      InCol_Cpmin - The column in the airfoil tables that contains the Cpmin coefficient; use zero if there is no Cpmin column (-)
{count}                      NumAFfiles  - Number of airfoil files used (-)
{files}
======  Rotor/Blade Properties  =====================================================================
False                  UseBlCm     - Include aerodynamic pitching moment in calculations? (flag)
"blade.dat" ADBlFile(1) - Name of file containing distributed aerodynamic properties for Blade #1 (-)
"blade.dat" ADBlFile(2) - Name of file containing distributed aerodynamic properties for Blade #2 (-) [unused if NumBl < 2]
"blade.dat" ADBlFile(3) - Name of file containing distributed aerodynamic properties for Blade #3 (-) [unused if NumBl < 3]
======  Hub Properties ============================================================================== [used only when MHK=1 or 2]
0                      VolHub      - Hub volume (m^3)
0                      HubCenBx    - Hub center of buoyancy x direction offset (m)
======  Nacelle Properties ========================================================================== [used only when MHK=1 or 2]
0                      VolNac      - Nacelle volume (m^3)
0.0, 0.0, 0.0          NacCenB     - Position of nacelle center of buoyancy from yaw bearing in nacelle coordinates (m)
0, 0, 0                NacArea     - Projected area of the nacelle in X, Y, Z in the nacelle coordinate system (m^2)
0, 0, 0                NacCd       - Drag coefficient for the nacelle areas defined above (-)
0, 0, 0                NacDragAC   - Position of aerodynamic center of nacelle drag in nacelle coordinates (m)
======  Tail Fin Aerodynamics =======================================================================
False                  TFinAero    - Calculate tail fin aerodynamics model (flag)
"unused"               TFinFile    - Input file for tail fin aerodynamics [used only when TFinAero=True]
======  Tower Influence and Aerodynamics ============================================================
0                      NumTwrNds   - Number of tower nodes used in the analysis (-) [used only when TwrPotent/=0, TwrShadow/=0, or TwrAero=True]
TwrElev        TwrDiam        TwrCd          TwrTI          TwrCb          TwrCp          TwrCa
(m)            (m)            (-)            (-)            (-)            (-)            (-)
======  Outputs  ====================================================================================
False                  SumPrint    - Generate a summary file listing input options and interpolated properties to "<rootname>.AD.sum"? (flag)
0                      NBlOuts     - Number of blade node outputs [0 - 9] (-)
1, 9, 19               BlOutNd     - Blade nodes whose values will be output (-)
0                      NTwOuts     - Number of tower node outputs [0 - 9] (-)
1, 2, 6                TwOutNd     - Tower nodes whose values will be output (-)
                       OutList     - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
{outputs}END of OutList section (the word "END" must appear in the first 3 columns of the last OutList line)
======  Node Outputs  ===============================================================================
0                      BldNd_BladesOut  - Number of blades to output all node information at.  Up to number of blades on turbine. (-)
"ALL"                  BldNd_BlOutNd   - Specify a portion of the nodes to output. {{"ALL", "Tip", "Root", or a list of node numbers}} (-)
                       OutList_Nodal - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
END (the word "END" must appear in the first 3 columns of this last OutList line in the optional nodal output section)
====================================================================================================
"""


def _blade(span, twist, chord):
    rows = '\n'.join(f'{_num(s)}  0  0  0  {_num(t)}  {_num(c)}  {i + 1}  0.0  0.0  0.0  0.0' for i, (s, t, c) in enumerate(zip(span, twist, chord)))
    return f"""------- AERODYN v15.00.* BLADE DEFINITION INPUT FILE -------------------------------------
Nova blade: span from the blade root, straight blade, no sweep or curvature.
======  Blade Properties =================================================================
{len(span)}   NumBlNds           - Number of blade nodes used in the analysis (-)
  BlSpn        BlCrvAC        BlSwpAC        BlCrvAng       BlTwist        BlChord          BlAFID    t_c      BlCb     BlCenBn     BlCenBt
   (m)           (m)            (m)            (deg)         (deg)           (m)              (-)     (-)      (-)      (m)         (m)
{rows}
"""


def _airfoil(name, reynolds, cl, cd):
    table = '\n'.join(f'{a:10.2f} {l:10.5f} {d:10.5f}' for a, l, d in zip(GRID_DEG, cl, cd))
    return f"""! ------------ AirfoilInfo v1.01.x Input File ----------------------------------
! {name}: Nova polar evaluated at Re = {reynolds:.4g}; columns Alpha, Cl, Cd (no pitching moment).
! ------------------------------------------------------------------------------
"DEFAULT"     InterpOrd         ! Interpolation order to use for quasi-steady table lookup {{1=linear; 3=cubic spline; "default"}}
          1   NonDimArea        ! The non-dimensional area of the airfoil (area/chord^2)
          0   NumCoords         ! The number of coordinates in the airfoil shape file.
"unused"      BL_file           ! The file name including the boundary layer characteristics of the profile.
          1   NumTabs           ! Number of airfoil tables in this file.
! ------------------------------------------------------------------------------
! data for table 1
! ------------------------------------------------------------------------------
{reynolds / 1e6:10.6g}   Re                ! Reynolds number in millions
          0   UserProp          ! User property (control) setting
False         InclUAdata        ! Is unsteady aerodynamics data included in this table?
!........................................
! Table of aerodynamics coefficients
{len(GRID_DEG):10d}   NumAlf            ! Number of data lines in the following table
!    Alpha      Cl      Cd
!    (deg)      (-)     (-)
{table}
"""


ED_OUTPUTS = ('Azimuth', 'RotSpeed', 'TipDxb1', 'TipDyb1', 'RootMEdg1', 'RootMFlp1', 'RootFxb1', 'RootFyb1',
              'TwrBsMxt', 'TwrBsMyt', 'TwrBsFxt', 'YawBrTDxp', 'YawBrTDyp')
STABILITY = 0.07  # time step limit as a fraction of the shortest enabled modal period


def _flag(value):
    return 'True' if value else 'False'


def _elastodyn(blades, tip, hub, rpm, pitch, hub_record, nacelle, tower, blade, settings):
    outputs = ''.join(f'"{name}"\n' for name in ED_OUTPUTS)
    hub_cm, tilt = hub_record['cm_downwind_m'], nacelle['shaft_tilt_deg']
    tower_top = tower['base_height_m'] + tower['height_m']
    row = lambda value, key, text: f'{value}   {key}  - {text}'  # noqa: E731
    return f"""------- ELASTODYN for OpenFAST INPUT FILE -------------------------------------------
Nova flexible rotor: prescribed rotor speed, blade and tower modes from the supplied distributions.
---------------------- SIMULATION CONTROL --------------------------------------
False         Echo        - Echo input data to "<RootName>.ech" (flag)
          3   Method      - Integration method: {{1: RK4, 2: AB4, or 3: ABM4}} (-)
{_num(settings['_dt'])}   DT          - Integration time step (s)
---------------------- DEGREES OF FREEDOM --------------------------------------
{_flag(settings['flap_dof'])}         FlapDOF1    - First flapwise blade mode DOF (flag)
{_flag(settings['flap_dof'])}         FlapDOF2    - Second flapwise blade mode DOF (flag)
{_flag(settings['edge_dof'])}         EdgeDOF     - First edgewise blade mode DOF (flag)
False         PitchDOF    - Blade pitch DOF (flag)
False         TeetDOF     - Rotor-teeter DOF (flag) [unused for 3 blades]
False         DrTrDOF     - Drivetrain rotational-flexibility DOF (flag)
False         GenDOF      - Generator DOF (flag)
False         YawDOF      - Yaw DOF (flag)
{_flag(settings['tower_fa_dof'])}         TwFADOF1    - First fore-aft tower bending-mode DOF (flag)
{_flag(settings['tower_fa_dof'])}         TwFADOF2    - Second fore-aft tower bending-mode DOF (flag)
{_flag(settings['tower_ss_dof'])}         TwSSDOF1    - First side-to-side tower bending-mode DOF (flag)
{_flag(settings['tower_ss_dof'])}         TwSSDOF2    - Second side-to-side tower bending-mode DOF (flag)
False         PtfmSgDOF   - Platform horizontal surge translation DOF (flag)
False         PtfmSwDOF   - Platform horizontal sway translation DOF (flag)
False         PtfmHvDOF   - Platform vertical heave translation DOF (flag)
False         PtfmRDOF    - Platform roll tilt rotation DOF (flag)
False         PtfmPDOF    - Platform pitch tilt rotation DOF (flag)
False         PtfmYDOF    - Platform yaw rotation DOF (flag)
---------------------- INITIAL CONDITIONS --------------------------------------
          0   OoPDefl     - Initial out-of-plane blade-tip displacement (meters)
          0   IPDefl      - Initial in-plane blade-tip deflection (meters)
{_num(pitch)}   BlPitch(1)  - Blade 1 initial pitch (degrees)
{_num(pitch)}   BlPitch(2)  - Blade 2 initial pitch (degrees)
{_num(pitch)}   BlPitch(3)  - Blade 3 initial pitch (degrees) [unused for 2 blades]
          0   TeetDefl    - Initial or fixed teeter angle (degrees) [unused for 3 blades]
          0   Azimuth     - Initial azimuth angle for blade 1 (degrees)
{_num(rpm)}   RotSpeed    - Initial or fixed rotor speed (rpm)
          0   NacYaw      - Initial or fixed nacelle-yaw angle (degrees)
          0   TTDspFA     - Initial fore-aft tower-top displacement (meters)
          0   TTDspSS     - Initial side-to-side tower-top displacement (meters)
          0   PtfmSurge   - Initial or fixed horizontal surge translational displacement of platform (meters)
          0   PtfmSway    - Initial or fixed horizontal sway translational displacement of platform (meters)
          0   PtfmHeave   - Initial or fixed vertical heave translational displacement of platform (meters)
          0   PtfmRoll    - Initial or fixed roll tilt rotational displacement of platform (degrees)
          0   PtfmPitch   - Initial or fixed pitch tilt rotational displacement of platform (degrees)
          0   PtfmYaw     - Initial or fixed yaw rotational displacement of platform (degrees)
---------------------- TURBINE CONFIGURATION -----------------------------------
{int(blades)}   NumBl       - Number of blades (-)
{_num(tip)}   TipRad      - The distance from the rotor apex to the blade tip (meters)
{_num(hub)}   HubRad      - The distance from the rotor apex to the blade root (meters)
{_num(hub_record['precone_deg'])}   PreCone(1)  - Blade 1 cone angle (degrees)
{_num(hub_record['precone_deg'])}   PreCone(2)  - Blade 2 cone angle (degrees)
{_num(hub_record['precone_deg'])}   PreCone(3)  - Blade 3 cone angle (degrees) [unused for 2 blades]
{_num(hub_cm)}   HubCM       - Distance from rotor apex to hub mass [positive downwind] (meters)
          0   UndSling    - Undersling length [distance from teeter pin to the rotor apex] (meters) [unused for 3 blades]
          0   Delta3      - Delta-3 angle for teetering rotors (degrees) [unused for 3 blades]
          0   AzimB1Up    - Azimuth value to use for I/O when blade 1 points up (degrees)
{_num(nacelle['overhang_m'])}   OverHang    - Distance from yaw axis to rotor apex [3 blades] or teeter pin [2 blades] (meters)
          0   ShftGagL    - Distance from rotor apex [3 blades] or teeter pin [2 blades] to shaft strain gages [positive for upwind rotors] (meters)
{_num(tilt)}   ShftTilt    - Rotor shaft tilt angle (degrees)
{_num(nacelle['cm_downwind_m'])}   NacCMxn     - Downwind distance from the tower-top to the nacelle CM (meters)
{_num(nacelle['cm_lateral_m'])}   NacCMyn     - Lateral  distance from the tower-top to the nacelle CM (meters)
{_num(nacelle['cm_up_m'])}   NacCMzn     - Vertical distance from the tower-top to the nacelle CM (meters)
          0   NcIMUxn     - Downwind distance from the tower-top to the nacelle IMU (meters)
          0   NcIMUyn     - Lateral  distance from the tower-top to the nacelle IMU (meters)
          0   NcIMUzn     - Vertical distance from the tower-top to the nacelle IMU (meters)
{_num(nacelle['tower_top_to_shaft_m'])}   Twr2Shft    - Vertical distance from the tower-top to the rotor shaft (meters)
{_num(tower_top)}   TowerHt     - Height of tower relative to ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] (meters)
{_num(tower['base_height_m'])}   TowerBsHt   - Height of tower base relative to ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] (meters)
          0   PtfmCMxt    - Downwind distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform CM (meters)
          0   PtfmCMyt    - Lateral distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform CM (meters)
          0   PtfmCMzt    - Vertical distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform CM (meters)
          0   PtfmRefxt   - Downwind distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform reference point (meters)
          0   PtfmRefyt   - Lateral distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform reference point (meters)
          0   PtfmRefzt   - Vertical distance from the ground level [onshore], MSL [offshore wind or floating platform], or seabed [fixed-bottom offshore] to the platform reference point (meters)
---------------------- MASS AND INERTIA ----------------------------------------
{_num(blade['tip_mass_kg'])}   TipMass(1)  - Tip-brake mass, blade 1 (kg)
{_num(blade['tip_mass_kg'])}   TipMass(2)  - Tip-brake mass, blade 2 (kg)
{_num(blade['tip_mass_kg'])}   TipMass(3)  - Tip-brake mass, blade 3 (kg) [unused for 2 blades]
          0   PBrIner(1)  - Pitch bearing inertia, blade 1 (kg m^2)
          0   PBrIner(2)  - Pitch bearing inertia, blade 2 (kg m^2)
          0   PBrIner(3)  - Pitch bearing inertia, blade 3 (kg m^2) [unused for 2 blades]
          0   BlPIner(1)  - Blade pitch inertia, blade 1 (kg m^2)
          0   BlPIner(2)  - Blade pitch inertia, blade 2 (kg m^2)
          0   BlPIner(3)  - Blade pitch inertia, blade 3 (kg m^2) [unused for 2 blades]
{_num(hub_record['mass_kg'])}   HubMass     - Hub mass (kg)
{_num(hub_record['inertia_kg_m2'])}   HubIner     - Hub inertia about rotor axis (2 or 3-blades) (kg m^2)
          0   HubIner_Teeter - Hub inertia about teeter axis (2-blades) (kg m^2)
          1   GenIner     - Generator inertia about HSS (kg m^2) (unused: rotor speed is prescribed)
{_num(nacelle['mass_kg'])}   NacMass     - Nacelle mass (kg)
{_num(nacelle['yaw_inertia_kg_m2'])}   NacYIner    - Nacelle inertia about yaw axis (kg m^2)
          0   YawBrMass   - Yaw bearing mass (kg)
          0   PtfmMass    - Platform mass (kg)
          0   PtfmRIner   - Platform inertia for roll tilt rotation about the platform CM (kg m^2)
          0   PtfmPIner   - Platform inertia for pitch tilt rotation about the platform CM (kg m^2)
          0   PtfmYIner   - Platform inertia for yaw rotation about the platform CM (kg m^2)
          0   PtfmXYIner  - Platform xy moment of inertia about the platform CM (=-int(xydm)) (kg m^2)
          0   PtfmYZIner  - Platform yz moment of inertia about the platform CM (=-int(yzdm)) (kg m^2)
          0   PtfmXZIner  - Platform xz moment of inertia about the platform CM (=-int(xzdm)) (kg m^2)
---------------------- BLADE ---------------------------------------------------
{ED_NODES}   BldNodes    - Number of blade nodes (per blade) used for analysis (-)
"{ED_BLADE}"    BldFile(1)  - Name of file containing properties for blade 1 (quoted string)
"{ED_BLADE}"    BldFile(2)  - Name of file containing properties for blade 2 (quoted string)
"{ED_BLADE}"    BldFile(3)  - Name of file containing properties for blade 3 (quoted string) [unused for 2 blades]
---------------------- ROTOR-TEETER --------------------------------------------
          0   TeetMod     - Rotor-teeter spring/damper model {{0: none, 1: standard, 2: user-defined from routine UserTeet}} (switch) [unused for 3 blades]
          0   TeetDmpP    - Rotor-teeter damper position (degrees) [used only for 2 blades and when TeetMod=1]
          0   TeetDmp     - Rotor-teeter damping constant (N-m/(rad/s)) [used only for 2 blades and when TeetMod=1]
          0   TeetCDmp    - Rotor-teeter rate-independent Coulomb-damping moment (N-m) [used only for 2 blades and when TeetMod=1]
          0   TeetSStP    - Rotor-teeter soft-stop position (degrees) [used only for 2 blades and when TeetMod=1]
          0   TeetHStP    - Rotor-teeter hard-stop position (degrees) [used only for 2 blades and when TeetMod=1]
          0   TeetSSSp    - Rotor-teeter soft-stop linear-spring constant (N-m/rad) [used only for 2 blades and when TeetMod=1]
          0   TeetHSSp    - Rotor-teeter hard-stop linear-spring constant (N-m/rad) [used only for 2 blades and when TeetMod=1]
---------------------- YAW-FRICTION --------------------------------------------
          0   YawFrctMod  - Yaw-friction model {{0: none, 1: friction independent of yaw-bearing force and bending moment, 2: friction with Coulomb damping dependent on yaw-bearing force and bending moment}} (switch)
          0   M_CSmax     - Maximum static Coulomb friction torque (N-m)
          0   M_FCSmax    - Maximum static Coulomb friction torque proportional to yaw bearing shear force (N-m/N)
          0   M_MCSmax    - Maximum static Coulomb friction torque proportional to yaw bearing bending moment (N-m/N-m)
          0   M_CD        - Dynamic Coulomb friction moment (N-m)
          0   M_FCD       - Dynamic Coulomb friction moment proportional to yaw bearing shear force (N-m/N)
          0   M_MCD       - Dynamic Coulomb friction moment proportional to yaw bearing bending moment (N-m/N-m)
          0   sig_v       - Linear viscous friction coefficient (N-m/(rad/s))
          0   sig_v2      - Quadratic viscous friction coefficient (N-m/(rad/s)^2)
          0   OmgCut      - Yaw angular velocity cutoff below which viscous friction is linearized (rad/s)
---------------------- DRIVETRAIN ----------------------------------------------
        100   GBoxEff     - Gearbox efficiency (%)
          1   GBRatio     - Gearbox ratio (-)
    1.0E+08   DTTorSpr    - Drivetrain torsional spring (N-m/rad) (unused: DrTrDOF is off)
    1.0E+05   DTTorDmp    - Drivetrain torsional damper (N-m/(rad/s)) (unused: DrTrDOF is off)
---------------------- FURLING -------------------------------------------------
False         Furling     - Read in additional model properties for furling turbine (flag) [must currently be FALSE)
"unused"      FurlFile    - Name of file containing furling properties (quoted string) [unused when Furling=False]
---------------------- TOWER ---------------------------------------------------
{ED_NODES}   TwrNodes    - Number of tower nodes used for analysis (-)
"{ED_TOWER}"    TwrFile     - Name of file containing tower properties (quoted string)
---------------------- OUTPUT --------------------------------------------------
False         SumPrint    - Print summary data to "<RootName>.sum" (flag)
          1   OutFile     - Switch to determine where output will be placed: {{1: in module output file only; 2: in glue code output file only; 3: both}} (currently unused)
True          TabDelim    - Use tab delimiters in text tabular output file? (flag) (currently unused)
"ES10.3E2"    OutFmt      - Format used for text tabular output (except time).  Resulting field should be 10 characters. (quoted string) (currently unused)
          0   TStart      - Time to begin tabular output (s) (currently unused)
          1   DecFact     - Decimation factor for tabular output {{1: output every time step}} (-) (currently unused)
          0   NTwGages    - Number of tower nodes that have strain gages for output [0 to 9] (-)
          0   TwrGagNd    - List of tower nodes that have strain gages [1 to TwrNodes] (-) [unused if NTwGages=0]
          0   NBlGages    - Number of blade nodes that have strain gages for output [0 to 9] (-)
          1   BldGagNd    - List of blade nodes that have strain gages [1 to BldNodes] (-) [unused if NBlGages=0]
              OutList     - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
{outputs}END of OutList section (the word "END" must appear in the first 3 columns of the last OutList line)
====== Outputs for all blade stations (same ending as above for Spn1.... =========================== [optional section]
          0   BldNd_BladesOut     - Number of blades to output all node information at.  Up to number of blades on turbine. (-)
"All"         BldNd_BlOutNd       - Future feature will allow selecting a portion of the nodes to output.  Not implemented yet. (-)
              OutList             - The next line(s) contains a list of output parameters.  See OutListParameters.xlsx for a listing of available output channels, (-)
END (the word "END" must appear in the first 3 columns of this last OutList line in the optional nodal output section)
----------------------------------------------------------------
"""


def _shape_rows(prefix, label, coefficients):
    return ''.join(f'{c:.10g}   {prefix}({k})  - {label}, coeff of x^{k}\n' for c, k in zip(coefficients, (2, 3, 4, 5, 6)))


def _ed_blade(blade, twist_at, modes):
    rows = '\n'.join(f'{x:.10g}  {twist_at(x):.10g}  {m:.10g}  {fl:.10g}  {ed:.10g}' for x, m, fl, ed in blade['stations'])
    return f"""------- ELASTODYN V1.00.* INDIVIDUAL BLADE INPUT FILE --------------------------
Nova blade structure; mode shapes computed by Nova from the distributions below (non-rotating Euler-Bernoulli cantilever).
---------------------- BLADE PARAMETERS ----------------------------------------
{len(blade['stations'])}   NBlInpSt    - Number of blade input stations (-)
{blade['flap_damping_pct']:.10g}   BldFlDmp(1) - Blade flap mode #1 structural damping in percent of critical (%)
{blade['flap_damping_pct']:.10g}   BldFlDmp(2) - Blade flap mode #2 structural damping in percent of critical (%)
{blade['edge_damping_pct']:.10g}   BldEdDmp(1) - Blade edge mode #1 structural damping in percent of critical (%)
---------------------- BLADE ADJUSTMENT FACTORS --------------------------------
          1   FlStTunr(1) - Blade flapwise modal stiffness tuner, 1st mode (-)
          1   FlStTunr(2) - Blade flapwise modal stiffness tuner, 2nd mode (-)
          1   AdjBlMs     - Factor to adjust blade mass density (-)
          1   AdjFlSt     - Factor to adjust blade flap stiffness (-)
          1   AdjEdSt     - Factor to adjust blade edge stiffness (-)
---------------------- DISTRIBUTED BLADE PROPERTIES ----------------------------
        BlFract               StrcTwst               BMassDen               FlpStff                 EdgStff
          (-)                   (deg)                 (kg/m)                 (Nm^2)                  (Nm^2)
{rows}
---------------------- BLADE MODE SHAPES ---------------------------------------
{_shape_rows('BldFl1Sh', 'Flap mode 1', modes['flap1'])}{_shape_rows('BldFl2Sh', 'Flap mode 2', modes['flap2'])}{_shape_rows('BldEdgSh', 'Edge mode 1', modes['edge1'])}"""


def _ed_tower(tower, modes):
    rows = '\n'.join(f'{x:.10g}  {m:.10g}  {fa:.10g}  {ss:.10g}' for x, m, fa, ss in tower['stations'])
    d = tower['damping_pct']
    return f"""------- ELASTODYN V1.00.* TOWER INPUT FILE -------------------------------------
Nova tower structure; mode shapes computed by Nova with the rotor and nacelle mass lumped at the tower top.
---------------------- TOWER PARAMETERS ----------------------------------------
{len(tower['stations'])}   NTwInpSt    - Number of input stations to specify tower geometry
{d:.10g}   TwrFADmp(1) - Tower 1st fore-aft mode structural damping ratio (%)
{d:.10g}   TwrFADmp(2) - Tower 2nd fore-aft mode structural damping ratio (%)
{d:.10g}   TwrSSDmp(1) - Tower 1st side-to-side mode structural damping ratio (%)
{d:.10g}   TwrSSDmp(2) - Tower 2nd side-to-side mode structural damping ratio (%)
---------------------- TOWER ADJUSTMUNT FACTORS --------------------------------
          1   FAStTunr(1) - Tower fore-aft modal stiffness tuner, 1st mode (-)
          1   FAStTunr(2) - Tower fore-aft modal stiffness tuner, 2nd mode (-)
          1   SSStTunr(1) - Tower side-to-side stiffness tuner, 1st mode (-)
          1   SSStTunr(2) - Tower side-to-side stiffness tuner, 2nd mode (-)
          1   AdjTwMa     - Factor to adjust tower mass density (-)
          1   AdjFASt     - Factor to adjust tower fore-aft stiffness (-)
          1   AdjSSSt     - Factor to adjust tower side-to-side stiffness (-)
---------------------- DISTRIBUTED TOWER PROPERTIES ----------------------------
  HtFract       TMassDen         TwFAStif       TwSSStif
   (-)           (kg/m)           (Nm^2)         (Nm^2)
{rows}
---------------------- TOWER FORE-AFT MODE SHAPES ------------------------------
{_shape_rows('TwFAM1Sh', 'Mode 1', modes['fa1'])}{_shape_rows('TwFAM2Sh', 'Mode 2', modes['fa2'])}---------------------- TOWER SIDE-TO-SIDE MODE SHAPES --------------------------
{_shape_rows('TwSSM1Sh', 'Mode 1', modes['ss1'])}{_shape_rows('TwSSM2Sh', 'Mode 2', modes['ss2'])}"""


def _structural_modes(structure, rotor_length, rotor_mass, settings):
    blade, tower, nacelle = structure['blade'], structure['tower'], structure['nacelle']
    fraction, mass, flap, edge = (np.array(c) for c in zip(*blade['stations']))
    found, assumptions = {}, []
    top_mass = nacelle['mass_kg'] + rotor_mass

    def one(name, x, m, k, length, tip, count):
        f, nodes, shapes = beam_modes.cantilever_modes(x, m, k, length, tip, modes=count)
        out = []
        for i in range(count):
            c, rms, worst = beam_modes.polynomial_shape(nodes, shapes[i])
            if rms > 0.03:
                raise CaseError(f'The {name} mode {i + 1} cannot be represented by the ElastoDyn polynomial '
                                f'(rms error {rms:.3f}); smooth the stiffness and mass distributions')
            out.append((c, float(f[i]), rms))
        return out

    flap_modes = one('blade flap', fraction, mass, flap, rotor_length, blade['tip_mass_kg'], 2)
    edge_modes = one('blade edge', fraction, mass, edge, rotor_length, blade['tip_mass_kg'], 1)
    tx, tm, tfa, tss = (np.array(c) for c in zip(*tower['stations']))
    fa_modes = one('tower fore-aft', tx, tm, tfa, tower['height_m'], top_mass, 2)
    ss_modes = one('tower side-to-side', tx, tm, tss, tower['height_m'], top_mass, 2)
    found['coefficients'] = {'flap1': flap_modes[0][0], 'flap2': flap_modes[1][0], 'edge1': edge_modes[0][0],
                             'fa1': fa_modes[0][0], 'fa2': fa_modes[1][0], 'ss1': ss_modes[0][0], 'ss2': ss_modes[1][0]}
    found['frequencies_hz'] = {'blade_flap1': flap_modes[0][1], 'blade_flap2': flap_modes[1][1], 'blade_edge1': edge_modes[0][1],
                               'tower_fa1': fa_modes[0][1], 'tower_fa2': fa_modes[1][1], 'tower_ss1': ss_modes[0][1], 'tower_ss2': ss_modes[1][1]}
    found['fit_rms'] = {k: float(max(m[2] for m in v)) for k, v in
                        {'blade_flap': flap_modes, 'blade_edge': edge_modes, 'tower_fa': fa_modes, 'tower_ss': ss_modes}.items()}
    enabled = []
    if settings['flap_dof']:
        enabled += [flap_modes[1][1]]
    if settings['edge_dof']:
        enabled += [edge_modes[0][1]]
    if settings['tower_fa_dof']:
        enabled += [fa_modes[1][1]]
    if settings['tower_ss_dof']:
        enabled += [ss_modes[1][1]]
    found['highest_enabled_hz'] = max(enabled) if enabled else 0.0
    assumptions.append('Mode shapes: non-rotating Euler-Bernoulli cantilever finite elements, fitted with the ElastoDyn x^2…x^6 polynomial; '
                       'tower modes include the nacelle and rotor mass lumped at the tower top, without rotary inertia')
    assumptions.append(f'Structural damping: blade {blade["flap_damping_pct"]:g} % flap / {blade["edge_damping_pct"]:g} % edge, '
                       f'tower {tower["damping_pct"]:g} % of critical (from the blocks)')
    assumptions.append('Blade principal axes follow the aerodynamic twist (structural twist = aerodynamic twist)')
    return found, assumptions


def write_rigid_case(spec, directory, settings=None):
    """Rigid rotor: Simplified ElastoDyn, no structure."""
    return write_case(spec, directory, settings, None)


def write_case(spec, directory, settings=None, structure=None):
    """Write the case into `directory`; return its description (paths, operating point, modes, case hash).

    Without `structure` the rotor is rigid (Simplified ElastoDyn). With the hub, nacelle, tower and blade
    records of `openfast_structure` the case is a full ElastoDyn model at prescribed rotor speed.
    """
    settings = _settings(settings)
    structure = {k: v for k, v in (structure or {}).items() if v is not None}
    flexible = bool(structure)
    if flexible:
        lacking = openfast_structure.missing(structure)
        if lacking:
            raise CaseError('A flexible OpenFAST model also needs: ' + ', '.join(lacking))
    root = FLEX if flexible else ROOT
    built, rotor, fluid = rotors.build(spec)
    if built['kind'] != 'hawt':
        raise CaseError('OpenFAST cases are generated for horizontal-axis wind turbines only')
    speed, rpm = rotors.resolve_operating(built, rotor)
    if rpm <= 0 or speed <= 0:
        raise CaseError('The OpenFAST case needs a positive wind speed and rotor speed')
    tip, hub = float(rotor.tip_radius_m), float(rotor.hub_radius_m)
    r, chord, twist = (np.asarray(a, dtype=float) for a in (rotor.radius_m, rotor.chord_m, rotor.twist_deg))
    # AeroDyn needs nodes from the root to the tip; extend flat when the Nova stations stop short.
    if r[0] > hub + 1e-9:
        r, chord, twist = np.r_[hub, r], np.r_[chord[0], chord], np.r_[twist[0], twist]
    if r[-1] < tip - 1e-9:
        r, chord, twist = np.r_[r, tip], np.r_[chord, chord[-1]], np.r_[twist, twist[-1]]
    r[0], r[-1] = hub, tip
    omega = rpm * 2 * math.pi / 60
    relative_speed = np.hypot(speed, omega * r)
    reynolds = fluid.density_kg_m3 * relative_speed * np.maximum(chord, 1e-6) / fluid.viscosity_pa_s
    pitch = float(built['geometry'].get('pitch_deg', 0.0))
    fluid_values = {'_rho': _num(fluid.density_kg_m3), '_nu': _num(fluid.viscosity_pa_s / fluid.density_kg_m3),
                    '_a': _num(fluid.speed_of_sound_m_s), '_p': _num(fluid.ambient_pressure_pa), '_root': root}
    extra, assumptions, modes = {}, [], None
    if flexible:
        hub_r, nac, tower, blade = structure['hub'], structure['nacelle'], structure['tower'], structure['blade']
        length = tip - hub
        fraction, mass = np.array([row[0] for row in blade['stations']]), np.array([row[1] for row in blade['stations']])
        blade_mass = float(np.trapezoid(mass, fraction) * length)
        rotor_mass = hub_r['mass_kg'] + rotor.blades * (blade_mass + blade['tip_mass_kg'])
        modes, assumptions = _structural_modes(structure, length, rotor_mass, settings)
        dt = settings['dt_s']
        if modes['highest_enabled_hz'] > 0:
            limit = STABILITY / modes['highest_enabled_hz']
            if dt > limit:
                assumptions.append(f'Time step reduced from {dt:g} s to {limit:.4g} s: {STABILITY:g} of the shortest enabled modal period '
                                   f'({modes["highest_enabled_hz"]:.3g} Hz)')
                dt = limit
        if settings['duration_s'] / dt > 2_000_000:
            raise CaseError('The run would need more than two million time steps')
        hub_height = tower['base_height_m'] + tower['height_m'] + nac['tower_top_to_shaft_m']
        resolved = {**settings, 'dt_s': dt, '_dt': dt, 'hub_height_m': hub_height, '_elast': 1, '_edfile': f'{root}_ElastoDyn.dat', **fluid_values}
        twist_at = lambda x: float(np.interp(x, (r - hub) / length, twist))  # noqa: E731
        extra = {f'{root}_ElastoDyn.dat': _elastodyn(rotor.blades, tip, hub, rpm, pitch, hub_r, nac, tower, blade, resolved),
                 ED_BLADE: _ed_blade(blade, twist_at, modes['coefficients']), ED_TOWER: _ed_tower(tower, modes['coefficients'])}
        if rotor.blades != 3:
            assumptions.append(f'{int(rotor.blades)} blades with a rigid hub (no teeter degree of freedom)')
        assumptions.append('Rotor speed is prescribed (no generator, drivetrain or controller dynamics)')
    else:
        overhang = settings['overhang_m'] if settings['overhang_m'] is not None else -0.05 * tip
        hub_height = settings['hub_height_m'] if settings['hub_height_m'] is not None else max(1.5 * tip, tip + 1.0)
        twr2shft = 0.05 * tip
        resolved = {**settings, 'overhang_m': overhang, 'hub_height_m': hub_height, '_twr2shft': twr2shft, '_tower_ht': hub_height - twr2shft,
                    '_dt': settings['dt_s'], '_elast': 3, '_edfile': f'{root}_SED.dat', **fluid_values}
        if resolved['_tower_ht'] <= 0:
            raise CaseError('hub_height_m must exceed the tower-top offset')
        extra = {f'{root}_SED.dat': _sed(rotor.blades, tip, hub, rpm, pitch, resolved)}
    directory = Path(directory)
    (directory / 'airfoils').mkdir(parents=True, exist_ok=True)
    files = {f'{root}.fst': _fst(resolved), f'{root}_InflowWind.dat': _inflow(speed, hub_height),
             f'{root}_AeroDyn.dat': _aerodyn(len(r), built['corrections']), 'blade.dat': _blade(r - hub, twist, chord), **extra}
    for i in range(len(r)):
        cl, cd = rotor.section(GRID_DEG, np.full_like(GRID_DEG, reynolds[i]), np.full_like(GRID_DEG, r[i]))
        files[f'airfoils/station_{i + 1:02d}.dat'] = _airfoil(f'Station {i + 1} (r = {r[i]:.4g} m)', reynolds[i], cl, cd)
    manifest = {'model': 'flexible' if flexible else 'rigid', 'assumptions': assumptions,
                'frequencies_hz': modes['frequencies_hz'] if modes else None, 'mode_fit_rms': modes['fit_rms'] if modes else None}
    for name, text in files.items():
        (directory / name).write_text(text)
    digest = hashlib.sha256(json.dumps({k: files[k] for k in sorted(files)}, sort_keys=True).encode()).hexdigest()
    return {'case_directory': str(directory.resolve()), 'input_file': f'{root}.fst', 'output_file': f'{root}.outb', 'files': sorted(files),
            'model': manifest['model'], 'assumptions': assumptions, 'frequencies_hz': manifest['frequencies_hz'],
            'operating': {'wind_speed_m_s': speed, 'rpm': rpm, 'tip_speed_ratio': omega * tip / speed, 'pitch_deg': pitch},
            'rotor': {'blades': int(rotor.blades), 'radius_m': tip, 'hub_radius_m': hub, 'stations': len(r)},
            'settings': {k: resolved[k] for k in (*SETTINGS, *DOF_SETTINGS)}, 'case_hash': digest}
