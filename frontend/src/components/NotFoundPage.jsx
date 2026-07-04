import { useNavigate } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-4 font-sans selection:bg-indigo-500 selection:text-white">
      <div className="w-full max-w-md bg-slate-900/50 backdrop-blur-md border border-slate-800 rounded-2xl p-8 shadow-2xl text-center relative overflow-hidden">

        {/* Top decorative gradient border */}
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-amber-500 via-rose-500 to-indigo-500" />

        {/* Alarm/Warning Icon */}
        <div className="mx-auto w-16 h-16 bg-rose-950/40 border border-rose-800/60 rounded-full flex items-center justify-center mb-6 animate-pulse">
          <ShieldAlert className="w-8 h-8 text-rose-500" />
        </div>

        <h1 className="text-4xl font-extrabold tracking-tight mb-2 text-white">404</h1>
        <h2 className="text-xl font-bold text-slate-350 mb-3 uppercase tracking-wider text-slate-200">Zone Not Found</h2>

        <p className="text-sm text-slate-400 mb-8 leading-relaxed">
          The coordinate grid, zone, or telemetry feed you are trying to access does not exist or is currently offline.
        </p>

        <button
          onClick={() => navigate('/')}
          className="w-full py-3 px-4 bg-indigo-650 hover:bg-indigo-600 text-white font-bold rounded-lg shadow-lg shadow-indigo-950/20 hover:shadow-indigo-500/20 transition-all border border-indigo-500/30 cursor-pointer flex justify-center items-center gap-2"
        >
          Return to Dashboard
        </button>

        <div className="mt-8 text-2xs text-slate-600 font-mono tracking-widest uppercase">
          RigVision-3D telemetry error
        </div>
      </div>
    </div>
  );
}
