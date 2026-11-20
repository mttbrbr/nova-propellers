"""Phase 4: thin-walled section properties, blade layup, CalculiX shell deck and adapter."""
import math
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

from nova.adapters.base import AdapterConfiguration, execute_adapter
from nova.adapters.calculix import CalculiXAdapter
from nova.blocks import engine, fem, structural
from nova.physics import blade_shell, rotors
from nova.physics.section_properties import properties

STEEL = {'E_pa': 2.0e11, 'G_pa': 8.0e10, 'density_kg_m3': 7850.0, 'thickness_m': 0.01}
DAT = """
     E I G E N V A L U E   O U T P U T

 MODE NO    EIGENVALUE                       FREQUENCY
                                     REAL PART            IMAGINARY PART
                           (RAD/TIME)      (CYCLES/TIME     (RAD/TIME)

      1   0.1579137E+04   0.3973835E+02   0.6324555E+01   0.0000000E+00
      2   0.6316547E+04   0.7947671E+02   0.1264911E+02   0.0000000E+00

     P A R T I C I P A T I O N   F A C T O R S
"""


class Sections(unittest.TestCase):
    def test_thin_circular_tube(self):
        p = properties(2.0, '0012', shell=STEEL, blend=0.0, points=400)
        r, t = 1.0, 0.01
        self.assertAlmostEqual(p['EI_flap_nm2'] / (math.pi * r**3 * t * 2e11), 1.0, delta=1e-4)
        self.assertAlmostEqual(p['EI_edge_nm2'] / (math.pi * r**3 * t * 2e11), 1.0, delta=1e-4)
        self.assertAlmostEqual(p['GJ_nm2'] / (2 * math.pi * r**3 * t * 8e10), 1.0, delta=1e-4)
        self.assertAlmostEqual(p['mass_kg_m'] / (2 * math.pi * r * t * 7850), 1.0, delta=1e-4)

    def test_web_splits_cells_and_matches_two_cell_theory(self):
        """A web on the diameter of a circular tube: by symmetry no shear flows in the web, GJ unchanged."""
        web = {**STEEL, 'position': 0.5}
        single = properties(2.0, '0012', shell=STEEL, blend=0.0, points=400)
        double = properties(2.0, '0012', shell=STEEL, webs=[web], blend=0.0, points=400)
        self.assertEqual(len(double['cells']), 2)
        self.assertAlmostEqual(double['GJ_nm2'] / single['GJ_nm2'], 1.0, delta=2e-3)

    def test_spar_caps_stiffen_flapwise(self):
        glass = {'E_pa': 2e10, 'G_pa': 4e9, 'density_kg_m3': 1900, 'thickness_m': 0.004}
        cap = {'E_pa': 4e10, 'G_pa': 4e9, 'density_kg_m3': 1900, 'thickness_m': 0.02, 'centre': 0.3, 'width': 0.2}
        bare = properties(1.0, '4418', shell=glass)
        capped = properties(1.0, '4418', shell=glass, spar_cap=cap)
        self.assertGreater(capped['EI_flap_nm2'], 2 * bare['EI_flap_nm2'])
        self.assertLess(capped['EI_flap_nm2'], capped['EI_edge_nm2'])


def _layup():
    return fem.blade_layup({'config': engine.BLOCKS['blade_layup']['defaults']}, {'spec': rotors.merged({'kind': 'hawt'})})


class Layup(unittest.TestCase):
    def test_layup_feeds_the_modal_blocks(self):
        out = _layup()
        blade = out['blade']
        self.assertIn('torsional_stiffness_nm2', blade['extended'])
        modes = structural.blade_modes({'config': {'flap_modes': 2, 'edge_modes': 1, 'torsion_modes': 1}},
                                       {'blade': blade, 'spec': rotors.merged({'kind': 'hawt'})})
        values = modes['values']
        self.assertLess(values['blade_flap1_hz'], values['blade_edge1_hz'])
        self.assertIn('blade_torsion1_hz', values)
        self.assertAlmostEqual(values['blade_mass_kg'], out['values']['blade_mass_kg'], delta=0.01 * out['values']['blade_mass_kg'])


class ShellDeck(unittest.TestCase):
    def test_deck_structure(self):
        layup = _layup()['layup']
        text, mesh = blade_shell.deck(layup, span_elements=10, perimeter_points=24, modes=6)
        self.assertIn('*FREQUENCY\n6', text)
        self.assertIn('*NSET, NSET=ROOT', text)
        self.assertEqual(text.count('*SHELL SECTION'), text.count('*MATERIAL'))
        rings = 11
        self.assertEqual(mesh['nodes'], rings * 24 + 2 * rings * 3)  # surface rings + 3 interior nodes per web per ring
        self.assertEqual(mesh['elements'], 10 * 24 + 2 * 10 * 4)
        coords = np.array([[float(v) for v in line.split(',')[1:]] for line in text.split('*NODE\n')[1].split('*ELEMENT')[0].strip().splitlines()])
        self.assertAlmostEqual(coords[:, 0].max(), layup['length_m'])

    def test_dat_parser(self):
        found = blade_shell.frequencies(DAT)
        self.assertEqual([m['mode'] for m in found], [1, 2])
        self.assertAlmostEqual(found[1]['frequency_hz'], 12.64911)


class FakeCalculiX(unittest.TestCase):
    """The adapter path (probe, staged deck, process, .dat parsing) with a stand-in executable."""

    def test_adapter_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'ccx'
            exe.write_text(textwrap.dedent(f'''\
                #!{sys.executable}
                import sys
                if sys.argv[1:] == ['-v']:
                    print('This is Version 2.21'); sys.exit(0)
                job = sys.argv[sys.argv.index('-i') + 1]
                assert open(job + '.inp').read().startswith('** Nova blade shell')
                open(job + '.dat', 'w').write({DAT!r})
                '''))
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            source = Path(tmp) / 'source'
            source.mkdir()
            text, mesh = blade_shell.deck(_layup()['layup'], span_elements=6, perimeter_points=16, modes=2)
            (source / 'blade.inp').write_text(text)
            output = execute_adapter(CalculiXAdapter(), AdapterConfiguration(exe), {'case_directory': str(source), 'input_file': 'blade.inp'},
                                     Path(tmp) / 'runs')
            result = fem.modes_outputs(output['data']['modes'], mesh)
            self.assertAlmostEqual(result['values']['shell_mode1_hz'], 6.324555)


@unittest.skipUnless(os.environ.get('NOVA_CCX'), 'Set NOVA_CCX to a CalculiX executable to run the real shell model')
class RealCalculiX(unittest.TestCase):
    def test_shell_and_beam_first_flap_agree(self):
        layup_out = _layup()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            text, mesh = blade_shell.deck(layup_out['layup'], span_elements=40, perimeter_points=48, modes=4)
            (source / 'blade.inp').write_text(text)
            output = execute_adapter(CalculiXAdapter(), AdapterConfiguration(Path(os.environ['NOVA_CCX'])),
                                     {'case_directory': str(source), 'input_file': 'blade.inp'}, Path(tmp) / 'runs')
        beam = structural.blade_modes({'config': {}}, {'blade': layup_out['blade'], 'spec': rotors.merged({'kind': 'hawt'})})
        first = output['data']['modes'][0]['frequency_hz']
        self.assertAlmostEqual(first, beam['values']['blade_flap1_hz'], delta=0.15 * first)


if __name__ == '__main__':
    unittest.main()
