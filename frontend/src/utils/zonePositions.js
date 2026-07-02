/**
 * RigVision-3D — Zone Position Definitions
 *
 * Frontend mirror of cad/zone_definitions.json.
 * Two stacked rooms, no corridor:
 *   - Room A (zone_a) on the ground floor (floor 0), y ∈ [0, 3.4]
 *   - Room B (zone_b) on the first floor (floor 1), y ∈ [3.4, 6.8], directly above A
 * Both rooms share the same 8×6m footprint (X ∈ [0,8], Z ∈ [0,6]); they differ only
 * in height. Each zone has 2 cameras with overlapping views (for stereo triangulation).
 *
 * `equipment[].position` is the mesh CENTRE (already includes the floor offset), so the
 * 3D scene can drop a prop straight at that point.
 */

export const ZONES = {
  zone_a: {
    name: 'Room A',
    floor: 0,
    center: [4, 1.7, 3],
    size: [8, 3.4, 6],
    min: [0, 0, 0],
    max: [8, 3.4, 6],
    color: '#4488ff',
    equipment: [
      { id: 'pump_01', name: 'Mud Pump #1', type: 'pump', position: [2.0, 0.6, 2.0], size: [1.6, 1.2, 1.1], color: '#6b7585' },
      { id: 'panel_01', name: 'Control Panel', type: 'control_panel', position: [6.6, 0.9, 5.2], size: [1.0, 1.8, 0.5], color: '#4a5666' },
      { id: 'pipe_rack_01', name: 'Pipe Rack', type: 'storage', position: [1.0, 1.1, 5.0], size: [0.9, 2.2, 1.6], color: '#7d7160' },
    ],
    // Two overlapping cameras per zone (cam0 + cam1 cover Room A).
    cameras: [
      { id: 'cam0', position: [0.4, 3.0, 0.4], lookAt: [5, 1, 4] },
      { id: 'cam1', position: [7.6, 3.0, 0.4], lookAt: [3, 1, 4] },
    ],
    sensors: [
      { id: 'temp_a', type: 'temperature', position: [2.0, 2.2, 2.0] },
      { id: 'gas_a', type: 'gas_h2s', position: [4.0, 0.3, 3.0] },
      { id: 'vib_a', type: 'vibration', position: [2.0, 0.6, 2.0] },
      { id: 'noise_a', type: 'noise', position: [5.0, 2.6, 4.0] },
      { id: 'pressure_a', type: 'pressure', position: [6.6, 1.0, 5.2] }
    ],
  },
  zone_b: {
    name: 'Room B',
    floor: 1,
    center: [4, 5.1, 3],
    size: [8, 3.4, 6],
    min: [0, 3.4, 0],
    max: [8, 6.8, 6],
    color: '#44ff88',
    equipment: [
      { id: 'compressor_01', name: 'Compressor', type: 'compressor', position: [2.5, 4.1, 2.0], size: [1.8, 1.4, 1.2], color: '#566472' },
      { id: 'wellhead_01', name: 'Wellhead', type: 'wellhead', position: [6.0, 4.7, 4.0], size: [1.0, 2.6, 1.0], color: '#8a7d6a' },
      { id: 'tool_cabinet_01', name: 'Tool Cabinet', type: 'storage', position: [1.0, 4.2, 5.0], size: [0.8, 1.6, 1.0], color: '#6f6555' },
    ],
    // Two overlapping cameras per zone (cam2 + cam3 cover Room B on the upper deck).
    cameras: [
      { id: 'cam2', position: [0.4, 6.4, 0.4], lookAt: [5, 4.4, 4] },
      { id: 'cam3', position: [7.6, 6.4, 0.4], lookAt: [3, 4.4, 4] },
    ],
    sensors: [
      { id: 'temp_b', type: 'temperature', position: [2.5, 5.6, 2.0] },
      { id: 'gas_b', type: 'gas_h2s', position: [6.0, 3.7, 4.0] },
      { id: 'vib_b', type: 'vibration', position: [2.5, 4.0, 2.0] },
      { id: 'noise_b', type: 'noise', position: [5.0, 6.0, 3.0] },
      { id: 'pressure_b', type: 'pressure', position: [6.0, 4.2, 4.0] }
    ],
  },
};

/**
 * Get zone color based on status (desaturated semantic palette).
 */
export function getZoneColor(status) {
  switch (status) {
    case 'warning': return '#d9a64e';
    case 'critical': return '#e06054';
    case 'normal':
    default: return '#46b17f';
  }
}

/**
 * Get zone opacity based on status.
 * Normal zones are mostly transparent, warnings/criticals are more visible.
 */
export function getZoneOpacity(status) {
  switch (status) {
    case 'warning': return 0.06;
    case 'critical': return 0.10;
    case 'normal':
    default: return 0.025;
  }
}
