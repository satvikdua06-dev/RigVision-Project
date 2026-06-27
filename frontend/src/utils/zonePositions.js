/**
 * RigVision-3D — Zone Position Definitions
 * 
 * Frontend mirror of cad/zone_definitions.json.
 * Defines zone bounding boxes, colors, and equipment positions
 * for the Three.js 3D scene.
 */

export const ZONES = {
  zone_a: {
    name: 'Room A',
    center: [2, 1.5, 2.5],
    size: [4, 3, 5],
    min: [0, 0, 0],
    max: [4, 3, 5],
    color: '#4488ff',
    equipment: [
      { id: 'pump_01', name: 'Mud Pump #1', position: [1.5, 0.5, 1.5], size: [1.2, 1.0, 0.8], color: '#667788' },
      { id: 'panel_01', name: 'Control Panel', position: [3.0, 0.9, 4.0], size: [0.8, 1.8, 0.4], color: '#445566' },
      { id: 'pipe_rack_01', name: 'Pipe Rack', position: [0.5, 1.0, 3.5], size: [0.6, 2.0, 1.0], color: '#887766' },
    ],
    camera: { id: 'cam0', position: [0.5, 2.5, 0.5], lookAt: [3, 1, 3] },
    sensors: [
      { id: 'temp_a1', type: 'temperature', position: [1.5, 2.0, 1.5] },
      { id: 'vib_a1', type: 'vibration', position: [1.5, 0.5, 1.5] },
      { id: 'noise_a1', type: 'noise', position: [2.0, 2.5, 2.5] },
      { id: 'gas_a1', type: 'gas_h2s', position: [2.0, 0.3, 2.5] },
      { id: 'temp_a2', type: 'temperature', position: [3.0, 1.5, 4.0] }
    ],
  },
  corridor: {
    name: 'Corridor',
    center: [5, 1.5, 2.5],
    size: [2, 3, 2],
    min: [4, 0, 1.5],
    max: [6, 3, 3.5],
    color: '#44aaff',
    equipment: [
      { id: 'fire_ext_01', name: 'Fire Extinguisher', position: [4.5, 0.3, 2.0], size: [0.2, 0.6, 0.2], color: '#cc3333' },
    ],
    camera: { id: 'cam1', position: [5.0, 2.5, 1.8], lookAt: [5.0, 1.0, 3.0] },
    sensors: [
      { id: 'gas_c1', type: 'gas_h2s', position: [5.0, 0.3, 2.5] },
      { id: 'noise_c1', type: 'noise', position: [5.0, 2.5, 2.5] }
    ],
  },
  zone_b: {
    name: 'Room B',
    center: [8, 1.5, 2.5],
    size: [4, 3, 5],
    min: [6, 0, 0],
    max: [10, 3, 5],
    color: '#44ff88',
    equipment: [
      { id: 'compressor_01', name: 'Compressor', position: [7.5, 0.6, 1.0], size: [1.5, 1.2, 1.0], color: '#556677' },
      { id: 'wellhead_01', name: 'Wellhead', position: [8.5, 1.25, 3.5], size: [0.8, 2.5, 0.8], color: '#998877' },
      { id: 'tool_cabinet_01', name: 'Tool Cabinet', position: [6.5, 0.75, 4.0], size: [0.6, 1.5, 0.8], color: '#776655' },
    ],
    camera: { id: 'cam2', position: [9.5, 2.5, 4.5], lookAt: [7.0, 1.0, 2.0] },
    sensors: [
      { id: 'temp_b1', type: 'temperature', position: [7.5, 1.0, 1.0] },
      { id: 'vib_b1', type: 'vibration', position: [7.5, 0.5, 1.0] },
      { id: 'noise_b1', type: 'noise', position: [8.0, 2.5, 2.5] },
      { id: 'gas_b1', type: 'gas_h2s', position: [8.5, 0.3, 3.5] },
      { id: 'temp_b2', type: 'temperature', position: [8.5, 1.5, 3.5] },
      { id: 'pressure_b1', type: 'pressure', position: [7.5, 0.8, 1.0] },
      { id: 'pressure_b2', type: 'pressure', position: [8.5, 1.0, 3.5] }
    ],
  },
};

/**
 * Get zone color based on status.
 * normal  → green (#00ff88)
 * warning → amber (#ffaa00)
 * critical → red  (#ff4455)
 */
export function getZoneColor(status) {
  switch (status) {
    case 'warning': return '#ffaa00';
    case 'critical': return '#ff4455';
    case 'normal':
    default: return '#00ff88';
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
