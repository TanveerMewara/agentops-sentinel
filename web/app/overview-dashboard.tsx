'use client';

import { AlertTriangle, ArrowUpRight, Bot, CheckCircle2, Clock3, Coins, ShieldAlert, Timer, Workflow } from 'lucide-react';
import { activityBars, costTrend, demoAgents, demoRuns } from './sentinel-demo';

const metrics = [
  ['Total runs', '12,842', '+12.4%', Workflow, 'crimson'],
  ['Success rate', '96.8%', '+1.6%', CheckCircle2, 'green'],
  ['Failed runs', '38', '-18.2%', AlertTriangle, 'amber'],
  ['Avg. latency', '2.4s', '-340ms', Timer, 'violet'],
  ['Token usage', '8.42M', '+7.1%', Bot, 'cyan'],
  ['Estimated cost', '$284.16', '+4.3%', Coins, 'blue'],
  ['Pending approvals', '7', '3 urgent', Clock3, 'amber'],
  ['Security incidents', '2', '1 high', ShieldAlert, 'crimson'],
] as const;

function Status({ value }: { value: string }) {
  return <span className={`snt-status snt-status--${value}`}>{value.replace('_', ' ')}</span>;
}

export default function OverviewDashboard({ onOpenRun, onNavigate }: { onOpenRun: (id: string) => void; onNavigate: (id: string) => void }) {
  return <div className="snt-stack">
    <section className="snt-hero">
      <div>
        <span className="snt-eyebrow"><span className="snt-live-dot" /> Operations live</span>
        <h2>Every agent. Every decision.<br/><em>Under control.</em></h2>
        <p>Watch execution, catch failures, measure quality, and govern high-risk actions from one control plane.</p>
      </div>
      <div className="snt-hero-orbit" aria-hidden="true"><span/><span/><span/><strong>24</strong><small>active runs</small></div>
    </section>

    <div className="snt-metric-grid">
      {metrics.map(([label, value, delta, Icon, tone]) => <article className={`snt-metric snt-tone-${tone}`} key={label}>
        <div className="snt-metric-head"><span>{label}</span><Icon size={16}/></div>
        <strong>{value}</strong><small>{delta}</small>
      </article>)}
    </div>

    <div className="snt-grid-2">
      <section className="snt-panel snt-chart-panel">
        <header><div><span className="snt-kicker">Execution pulse</span><h3>Run activity</h3></div><span className="snt-demo-chip">Demo Data · 24h</span></header>
        <div className="snt-bars" aria-label="Demo run activity chart">{activityBars.map((v,i)=><i key={i} style={{height:`${v}%`}} title={`${v} runs`}/>)}</div>
        <div className="snt-axis"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>Now</span></div>
      </section>
      <section className="snt-panel snt-chart-panel">
        <header><div><span className="snt-kicker">Spend guard</span><h3>Estimated cost</h3></div><strong>$284.16</strong></header>
        <svg className="snt-line-chart" viewBox="0 0 520 150" role="img" aria-label="Demo cost trend">
          <defs><linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7c3cff" stopOpacity=".42"/><stop offset="1" stopColor="#7c3cff" stopOpacity="0"/></linearGradient></defs>
          <path d={`M 8 142 ${costTrend.map((v,i)=>`L ${8+i*46} ${142-v*2.55}`).join(' ')} L 514 142 Z`} fill="url(#costFill)"/>
          <polyline points={costTrend.map((v,i)=>`${8+i*46},${142-v*2.55}`).join(' ')} fill="none" stroke="#a879ff" strokeWidth="3"/>
        </svg>
        <div className="snt-chart-legend"><span><i className="violet"/> Actual</span><span><i/> Budget threshold</span></div>
      </section>
    </div>

    <section className="snt-panel">
      <header><div><span className="snt-kicker">Most recent</span><h3>Live runs</h3></div><button className="snt-text-button" onClick={()=>onNavigate('runs')}>View all <ArrowUpRight size={14}/></button></header>
      <div className="snt-table-wrap"><table className="snt-table"><thead><tr><th>Run</th><th>Agent</th><th>Status</th><th>Active node</th><th>Duration</th><th>Cost</th></tr></thead><tbody>
        {demoRuns.map(run=><tr key={run.id} tabIndex={0} onClick={()=>onOpenRun(run.id)} onKeyDown={e=>{if(e.key==='Enter')onOpenRun(run.id)}}><td><code>{run.id}</code></td><td>{run.agent}</td><td><Status value={run.status}/></td><td>{run.node}</td><td>{run.duration}</td><td>{run.cost}</td></tr>)}
      </tbody></table></div>
    </section>

    <div className="snt-grid-2 snt-bottom-grid">
      <section className="snt-panel"><header><div><span className="snt-kicker">Fleet health</span><h3>Agents</h3></div><button className="snt-text-button" onClick={()=>onNavigate('agents')}>Manage <ArrowUpRight size={14}/></button></header>
        <div className="snt-agent-list">{demoAgents.slice(0,3).map(agent=><div className="snt-agent-row" key={agent.id}><span className={`snt-agent-icon snt-tone-${agent.tone}`}><Bot size={17}/></span><div><strong>{agent.name}</strong><small>{agent.framework} · {agent.version}</small></div><Status value={agent.status}/></div>)}</div>
      </section>
      <section className="snt-panel snt-alert-panel"><header><div><span className="snt-kicker">Needs attention</span><h3>Control queue</h3></div><span className="snt-demo-chip">4 open</span></header>
        <button onClick={()=>onNavigate('approvals')}><span className="snt-alert-icon amber"><Clock3 size={17}/></span><div><strong>Claims payout requires approval</strong><small>High-impact action · waiting 12 min</small></div><ArrowUpRight size={16}/></button>
        <button onClick={()=>onNavigate('incidents')}><span className="snt-alert-icon red"><ShieldAlert size={17}/></span><div><strong>Prompt injection signature detected</strong><small>Research Copilot · high severity</small></div><ArrowUpRight size={16}/></button>
      </section>
    </div>
  </div>;
}
