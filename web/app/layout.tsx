import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'AgentOps Sentinel | AI Agent Control Plane',
  description: 'Monitor, evaluate, secure, and govern AI agents from one production control plane.',
  openGraph: {
    title: 'AgentOps Sentinel | AI Agent Control Plane',
    description: 'Reliable execution for AI agents.',
    images: [{ url: '/agentops-sentinel-social-preview.png', width: 1200, height: 630 }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AgentOps Sentinel | AI Agent Control Plane',
    description: 'Reliable execution for AI agents.',
    images: ['/agentops-sentinel-social-preview.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body></html>;
}

