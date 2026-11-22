'use client';

import { useMemo, useState } from 'react';
import { Check, Focus, Minus, Plus, RotateCcw, X } from 'lucide-react';
import { workflowNodes } from './sentinel-demo';

export default function WorkflowGraph() {
  const [selected, setSelected] = useState('policy');
  const [zoom, setZoom] = useState(1);
  const node = workflowNodes.find(n=>n.id===selected) ?? workflowNodes[0];
  const paths = useMemo(()=>workflowNodes.filter(n=>n.parent).map(n=>({from:workflowNodes.find(x=>x.id===n.parent)!,to:n})),[]);
  return <section className="snt-run-layout">
    <div className="snt-panel snt-graph-panel">
      <header><div><span className="snt-kicker">Execution graph</span><h3>RUN-8F21A9</h3></div><span className="snt-status snt-status--running">running</span></header>
      <div className="snt-graph-toolbar" aria-label="Graph controls">
        <button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.7,z-.1))}><Minus size={15}/></button><span>{Math.round(zoom*100)}%</span><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(1.3,z+.1))}><Plus size={15}/></button><button aria-label="Fit graph" onClick={()=>setZoom(1)}><Focus size={15}/></button>
      </div>
      <div className="snt-graph-viewport">
        <div className="snt-graph-canvas" style={{transform:`scale(${zoom})`}}>
          <svg viewBox="0 0 1280 360" aria-hidden="true">{paths.map(({from,to})=><path key={to.id} d={`M ${from.x+128} ${from.y+28} C ${from.x+154} ${from.y+28}, ${to.x-24} ${to.y+28}, ${to.x} ${to.y+28}`} className={to.status==='running'?'active':''}/>)}</svg>
          {workflowNodes.map(n=><button key={n.id} className={`snt-node snt-node--${n.status} ${selected===n.id?'is-selected':''}`} style={{left:n.x,top:n.y}} onClick={()=>setSelected(n.id)} aria-pressed={selected===n.id}>
            <span>{n.status==='succeeded'?<Check size={12}/>:n.status==='failed'?<X size={12}/>:n.status==='retrying'?<RotateCcw size={12}/>:null}</span><small>{n.type}</small><strong>{n.label}</strong><em>{n.duration}</em>
          </button>)}
        </div>
      </div>
      <details className="snt-accessible-flow"><summary>Accessible execution order</summary><ol>{workflowNodes.map(n=><li key={n.id}><button onClick={()=>setSelected(n.id)}>{n.label} — {n.status}</button></li>)}</ol></details>
    </div>
    <aside className="snt-panel snt-node-detail"><span className="snt-kicker">Selected node</span><h3>{node.label}</h3><span className={`snt-status snt-status--${node.status}`}>{node.status.replace('_',' ')}</span>
      <dl><div><dt>Type</dt><dd>{node.type}</dd></div><div><dt>Duration</dt><dd>{node.duration}</dd></div>{node.model&&<div><dt>Model</dt><dd>{node.model}</dd></div>}{node.tool&&<div><dt>Tool</dt><dd>{node.tool}</dd></div>}{node.tokens&&<div><dt>Tokens</dt><dd>{node.tokens}</dd></div>}{node.cost&&<div><dt>Cost</dt><dd>{node.cost}</dd></div>}{node.evaluation&&<div><dt>Evaluation</dt><dd>{node.evaluation}</dd></div>}</dl>
      <div className="snt-log"><span>14:18:04.821</span><p>Guardrail evaluating output citations and tool provenance.</p><span>14:18:05.019</span><p>Awaiting policy result…</p></div>
    </aside>
  </section>;
}
