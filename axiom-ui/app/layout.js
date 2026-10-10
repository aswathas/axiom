import './globals.css';

export const metadata = {
  title: 'AXIOM — AI-Native Clinical Assistance',
  description:
    'Evidence-grounded clinical intelligence. Every claim cited; unverified claims do not appear.',
};

export const viewport = {
  themeColor: '#0f172a',
  colorScheme: 'light dark',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}