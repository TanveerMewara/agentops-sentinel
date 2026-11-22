import type { LucideIcon } from 'lucide-react';

export type ScreenId = 'overview' | 'agents' | 'traces' | 'runs' | 'evaluations' |
  'approvals' | 'security' | 'incidents' | 'failure-lab' | 'datasets' | 'settings';
export type Environment = 'Development' | 'Staging' | 'Production';
export type RunStatus = 'running' | 'succeeded' | 'failed' | 'blocked' | 'awaiting_approval' | 'retrying';
export type Tone = 'crimson' | 'violet' | 'cyan' | 'green' | 'amber' | 'blue';
export type NavItem = { id: ScreenId; label: string; icon: LucideIcon; badge?: number };
export type DemoRun = { id: string; agent: string; node: string; status: RunStatus; duration: string; tokens: string; cost: string; started: string; model: string; environment: Environment };
export type DemoAgent = { id: string; name: string; description: string; status: 'healthy' | 'degraded' | 'paused'; framework: string; version: string; lastRun: string; success: string; latency: string; cost: string; incidents: number; tone: Tone };
export type WorkflowNode = { id: string; label: string; type: string; status: RunStatus; x: number; y: number; duration: string; tokens?: string; cost?: string; model?: string; tool?: string; parent?: string; retry?: number; error?: string; evaluation?: string };
