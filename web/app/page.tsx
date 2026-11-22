import SentinelApp from './sentinel-app';
import type { ScreenId } from './sentinel-types';

const screens: ScreenId[] = ['overview','agents','traces','runs','evaluations','approvals','security','incidents','failure-lab','datasets','settings'];

export default async function Home({searchParams}:{searchParams:Promise<{screen?:string;view?:string}>}) {
  const params = await searchParams;
  const initialScreen = screens.includes(params.screen as ScreenId) ? params.screen as ScreenId : 'overview';
  return <SentinelApp initialScreen={initialScreen} initialRunDetail={params.view === 'run'} />;
}
