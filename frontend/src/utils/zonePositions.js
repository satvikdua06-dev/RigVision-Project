/**
 * RigVision-3D — Zone Position Definitions
 *
 * Frontend mirror of cad/zone_definitions.json.
 * Two stacked rooms, no corridor:
 *   - Room A (zone_a) on the ground floor (floor 0), y ∈ [0, 3]
 *   - Room B (zone_b) on the first floor (floor 1), y ∈ [3, 6], directly above A
 * Both rooms share the same 5×3.85m footprint (X ∈ [0,5], Z ∈ [0,3.85]).
 * Each zone has 2 cameras with overlapping views (for stereo triangulation).
 *
 * `equipment[].position` is the mesh CENTRE (already includes the floor offset), so the
 * 3D scene can drop a prop straight at that point.
 */

export const ZONES = {
  zone_a: {
    name: 'Room A',
    floor: 0,
    center: [2.5, 1.5, 1.925],
    size: [5, 3, 3.85],
    min: [0, 0, 0],
    max: [5, 3, 3.85],
    color: '#4488ff',
    equipment: [
      { id: 'pump_01',      name: 'Mud Pump #1',  type: 'pump',          position: [1.3, 0.6, 1.3], size: [1.0, 1.1, 0.7], color: '#6b7585' },
      { id: 'panel_01',     name: 'Control Panel', type: 'control_panel', position: [4.1, 0.9, 3.3], size: [0.7, 1.8, 0.4], color: '#4a5666' },
      { id: 'pipe_rack_01', name: 'Pipe Rack',     type: 'storage',       position: [0.6, 1.1, 3.2], size: [0.6, 1.8, 1.0], color: '#7d7160' },
    ],
    cameras: [
      { id: 'cam0', position: [0.3, 2.7, 0.3], lookAt: [3.1, 0.9, 2.6] },
      { id: 'cam1', position: [4.7, 2.7, 0.3], lookAt: [1.9, 0.9, 2.6] },
    ],
    sensors: [
      { id: 'temp_a',     type: 'temperature', position: [1.3, 1.9, 1.3] },
      { id: 'gas_a',      type: 'gas_h2s',     position: [2.5, 0.3, 1.9] },
      { id: 'vib_a',      type: 'vibration',   position: [1.3, 0.5, 1.3] },
      { id: 'noise_a',    type: 'noise',        position: [3.1, 2.3, 2.6] },
      { id: 'pressure_a', type: 'pressure',     position: [4.1, 0.9, 3.3] },
    ],
  },
  zone_b: {
    name: 'Room B',
    floor: 1,
    center: [2.5, 4.5, 1.925],
    size: [5, 3, 3.85],
    min: [0, 3, 0],
    max: [5, 6, 3.85],
    color: '#44ff88',
    equipment: [
      { id: 'compressor_01',  name: 'Compressor',        type: 'compressor',    position: [1.6, 3.7, 1.3], size: [1.1, 1.2, 0.8], color: '#566472' },
      { id: 'wellhead_01',    name: 'Wellhead Assembly', type: 'wellhead',      position: [3.8, 4.1, 2.6], size: [0.7, 2.2, 0.7], color: '#8a7d6a' },
      { id: 'tool_cabinet_01',name: 'Tool Cabinet',      type: 'storage',       position: [0.6, 3.7, 3.2], size: [0.6, 1.4, 0.7], color: '#6f6555' },
    ],
    cameras: [
      { id: 'cam2', position: [0.3, 5.7, 0.3], lookAt: [3.1, 3.9, 2.6] },
      { id: 'cam3', position: [4.7, 5.7, 0.3], lookAt: [1.9, 3.9, 2.6] },
    ],
    sensors: [
      { id: 'temp_b',     type: 'temperature', position: [1.6, 4.9, 1.3] },
      { id: 'gas_b',      type: 'gas_h2s',     position: [3.8, 3.3, 2.6] },
      { id: 'vib_b',      type: 'vibration',   position: [1.6, 3.5, 1.3] },
      { id: 'noise_b',    type: 'noise',        position: [3.1, 5.3, 1.9] },
      { id: 'pressure_b', type: 'pressure',     position: [3.8, 3.7, 2.6] },
    ],
  },
};

export function getZoneColor(status) {
  switch (status) {
    case 'warning': return '#d9a64e';
    case 'critical': return '#e06054';
    case 'normal':
    default: return '#46b17f';
  }
}

export function getZoneOpacity(status) {
  switch (status) {
    case 'warning': return 0.06;
    case 'critical': return 0.10;
    case 'normal':
    default: return 0.025;
  }
}
