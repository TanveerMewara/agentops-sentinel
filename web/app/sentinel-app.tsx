'use client';

import { useEffect, useState } from 'react';
import { Activity, AlertOctagon, Bell, Bot, Boxes, CheckSquare2, ChevronsUpDown, Command, Database, FlaskConical, LayoutDashboard, Menu, PlayCircle, Search, Settings, ShieldCheck, X } from 'lucide-react';
import OverviewDashboard from './overview-dashboard';
import { AgentsScreen, ApprovalsScreen, DatasetsScreen, EvaluationsScreen, FailureLabScreen, RunDetail, RunsScreen, SecurityScreen, SettingsScreen } from './product-screens';
import type { Environment, NavItem, ScreenId } from './sentinel-types';
import LegacyConsole from './legacy-console';
import './sentinel-ui.css';

const nav:NavItem[]=[
 {id:'overview',label:'Overview',icon:LayoutDashboard},{id:'agents',label:'Agents',icon:Bot},{id:'traces',label:'Live Traces',icon:Activity},{id:'runs',label:'Runs',icon:PlayCircle},
 {id:'evaluations',label:'Evaluations',icon:CheckSquare2},{id:'approvals',label:'Approvals',icon:Boxes,badge:7},{id:'security',label:'Security',icon:ShieldCheck},{id:'incidents',label:'Incidents',icon:AlertOctagon,badge:2},
 {id:'failure-lab',label:'Failure Lab',icon:FlaskConical},{id:'datasets',label:'Datasets',icon:Database},{id:'settings',label:'Settings',icon:Settings},
];
const headings:Record<ScreenId,string>={overview:'Operational overview',agents:'Agent registry',traces:'Live traces',runs:'Run history',evaluations:'Evaluations',approvals:'Approval queue',security:'Security posture',incidents:'Incident response','failure-lab':'Failure Lab',datasets:'Datasets',settings:'Settings'};
function Brand(){return <div className="snt-brand"><span><i/><i/><i/></span><div><strong>AgentOps</strong><em>Sentinel</em></div></div>}

export default function SentinelApp({initialScreen='overview',initialRunDetail=false}:{initialScreen?:ScreenId;initialRunDetail?:boolean}){
 const [screen,setScreen]=useState<ScreenId>(initialScreen); const [drawer,setDrawer]=useState(false); const [compact,setCompact]=useState(false); const [environment,setEnvironment]=useState<Environment>('Production'); const [palette,setPalette]=useState(false); const [legacy,setLegacy]=useState(false); const [runDetail,setRunDetail]=useState(initialRunDetail);
 useEffect(()=>{const handler=(e:KeyboardEvent)=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setPalette(v=>!v)}if(e.key==='Escape'){setPalette(false);setDrawer(false)}};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler)},[]);
 const go=(id:ScreenId)=>{setScreen(id);setRunDetail(false);setDrawer(false);window.scrollTo({top:0,behavior:'smooth'})};
 if(legacy)return <div className="snt-legacy"><button className="snt-back" onClick={()=>setLegacy(false)}><X size={16}/> Close connection console</button><LegacyConsole/></div>;
 const content=runDetail?<RunDetail/>:screen==='overview'?<OverviewDashboard onOpenRun={()=>setRunDetail(true)} onNavigate={id=>go(id as ScreenId)}/>:screen==='agents'?<AgentsScreen/>:screen==='traces'?<RunsScreen traces onOpen={()=>setRunDetail(true)}/>:screen==='runs'?<RunsScreen onOpen={()=>setRunDetail(true)}/>:screen==='evaluations'?<EvaluationsScreen/>:screen==='approvals'?<ApprovalsScreen/>:screen==='security'?<SecurityScreen/>:screen==='incidents'?<SecurityScreen incidents/>:screen==='failure-lab'?<FailureLabScreen/>:screen==='datasets'?<DatasetsScreen/>:<SettingsScreen onLegacy={()=>setLegacy(true)}/>;
 return <div className={`snt-app ${compact?'is-compact':''}`}>
  <a className="snt-skip" href="#main-content">Skip to content</a>{drawer&&<button className="snt-scrim" aria-label="Close navigation" onClick={()=>setDrawer(false)}/>} 
  <aside className={`snt-sidebar ${drawer?'is-open':''}`}><div className="snt-sidebar-head"><Brand/><button aria-label="Collapse sidebar" onClick={()=>setCompact(v=>!v)}><Menu size={18}/></button></div><nav aria-label="Primary navigation">{nav.map(({id,label,icon:Icon,badge})=><button key={id} className={screen===id&&!runDetail?'is-active':''} onClick={()=>go(id)} title={label}><Icon size={18}/><span>{label}</span>{badge&&<b>{badge}</b>}</button>)}</nav><div className="snt-system"><span/><div><strong>All systems operational</strong><small>Local pilot · Demo Data</small></div></div></aside>
  <div className="snt-shell"><header className="snt-topbar"><button className="snt-mobile-menu" aria-label="Open navigation" onClick={()=>setDrawer(true)}><Menu/></button><div className="snt-context"><button><span className="snt-workspace-mark">AS</span><span>Sentinel Lab</span><ChevronsUpDown size={14}/></button><label><span className={`snt-env-dot ${environment.toLowerCase()}`}/><select value={environment} onChange={e=>setEnvironment(e.target.value as Environment)} aria-label="Environment"><option>Development</option><option>Staging</option><option>Production</option></select></label></div><button className="snt-search" onClick={()=>setPalette(true)}><Search size={16}/><span>Search runs, agents, traces…</span><kbd>Ctrl K</kbd></button><div className="snt-top-actions"><span className="snt-demo-chip">Demo Data</span><button aria-label="Notifications" className="snt-notify"><Bell size={18}/><i/></button><button className="snt-avatar" aria-label="Open user menu">TM</button></div></header>
   <main id="main-content" className="snt-main"><div className="snt-page-head"><div><span>AgentOps Sentinel / {runDetail?'Run detail':headings[screen]}</span><h1>{runDetail?'Execution evidence':headings[screen]}</h1></div><div className="snt-live"><i/> Live updates</div></div>{content}</main>
  </div>
  {palette&&<div className="snt-dialog-layer" role="presentation" onMouseDown={()=>setPalette(false)}><div className="snt-command" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={e=>e.stopPropagation()}><label><Command size={18}/><input autoFocus placeholder="Go to a screen…"/><kbd>ESC</kbd></label><span>Navigate</span>{nav.slice(0,8).map(({id,label,icon:Icon})=><button key={id} onClick={()=>{go(id);setPalette(false)}}><Icon size={17}/>{label}<small>Open</small></button>)}</div></div>}
 </div>;
}
