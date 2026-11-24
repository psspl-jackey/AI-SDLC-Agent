export const metadata = { title: "{{project_name}}{{surface_title}}" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#f5f7fa" }}>{children}</body>
    </html>
  );
}
