import type { DemoAgent, DemoRun, WorkflowNode } from './sentinel-types';

export const demoRuns: DemoRun[] = [
  { id: 'RUN-8F21A9', agent: 'Support Triage', node: 'Policy check', status: 'running', duration: '1.8s', tokens: '1,284', cost: '$0.0038', started: '14:18:03', model: 'gpt-5-mini', environment: 'Production' },
  { id: 'RUN-54CD12', agent: 'Research Copilot', node: 'Evaluation', status: 'succeeded', duration: '4.2s', tokens: '3,841', cost: '$0.0184', started: '14:16:48', model: 'gpt-5', environment: 'Staging' },
  { id: 'RUN-A03E77', agent: 'Claims Reviewer', node: 'Human approval', status: 'awaiting_approval', duration: '12m', tokens: '2,102', cost: '$0.0091', started: '14:04:22', model: 'gpt-5-mini', environment: 'Production' },
  { id: 'RUN-19BEE4', agent: 'Data Analyst', node: 'SQL tool', status: 'failed', duration: '2.7s', tokens: '916', cost: '$0.0026', started: '13:58:11', model: 'gpt-5-mini', environment: 'Development' },
  { id: 'RUN-C4B908', agent: 'Release Guardian', node: 'Retry with backoff', status: 'retrying', duration: '8.6s', tokens: '1,672', cost: '$0.0057', started: '13:52:07', model: 'gpt-5-mini', environment: 'Staging' },
];
export const demoAgents: DemoAgent[] = [
  { id: 'support', name: 'Support Triage', description: 'Routes and resolves customer conversations.', status: 'healthy', framework: 'LangGraph', version: 'v2.4.1', lastRun: '12 sec ago', success: '98.4%', latency: '1.8s', cost: '$4.82', incidents: 0, tone: 'crimson' },
  { id: 'research', name: 'Research Copilot', description: 'Builds evidence-backed research briefs.', status: 'healthy', framework: 'OpenAI Agents', version: 'v1.8.0', lastRun: '2 min ago', success: '96.7%', latency: '4.2s', cost: '$12.18', incidents: 1, tone: 'violet' },
  { id: 'claims', name: 'Claims Reviewer', description: 'Reviews claims with mandatory approvals.', status: 'degraded', framework: 'Custom Python', version: 'v3.1.2', lastRun: '14 min ago', success: '91.2%', latency: '6.4s', cost: '$7.43', incidents: 2, tone: 'cyan' },
  { id: 'release', name: 'Release Guardian', description: 'Evaluates agent releases before deployment.', status: 'paused', framework: 'LangChain', version: 'v0.9.7', lastRun: '31 min ago', success: '94.9%', latency: '3.1s', cost: '$2.06', incidents: 1, tone: 'blue' },
];
export const workflowNodes: WorkflowNode[] = [
  { id: 'request', label: 'User request', type: 'input', status: 'succeeded', x: 70, y: 164, duration: '8ms', evaluation: 'Input accepted' },
  { id: 'router', label: 'Router', type: 'agent', status: 'succeeded', x: 240, y: 164, duration: '42ms', tokens: '128', model: 'gpt-5-mini', parent: 'request' },
  { id: 'planner', label: 'Planning agent', type: 'model', status: 'succeeded', x: 410, y: 82, duration: '684ms', tokens: '742', cost: '$0.0018', model: 'gpt-5-mini', parent: 'router' },
  { id: 'validate', label: 'Tool validation', type: 'policy', status: 'succeeded', x: 410, y: 246, duration: '11ms', parent: 'router', evaluation: 'Schema valid' },
  { id: 'tool', label: 'Knowledge search', type: 'tool', status: 'succeeded', x: 590, y: 82, duration: '312ms', tool: 'search_docs', parent: 'planner' },
  { id: 'policy', label: 'Policy check', type: 'guardrail', status: 'running', x: 590, y: 246, duration: 'Running', parent: 'validate', evaluation: 'Checking citations' },
  { id: 'approval', label: 'Human approval', type: 'approval', status: 'awaiting_approval', x: 770, y: 246, duration: 'Pending', parent: 'policy' },
  { id: 'response', label: 'Final response', type: 'output', status: 'blocked', x: 950, y: 164, duration: '-', parent: 'approval' },
  { id: 'evaluation', label: 'Evaluation', type: 'evaluation', status: 'blocked', x: 1125, y: 164, duration: '-', parent: 'response' },
];
export const activityBars = [38, 52, 44, 66, 58, 72, 63, 84, 70, 88, 76, 92, 81, 68, 74, 87, 79, 96, 83, 91, 72, 86, 78, 89];
export const costTrend = [18, 24, 21, 29, 27, 34, 31, 39, 36, 44, 41, 47];

