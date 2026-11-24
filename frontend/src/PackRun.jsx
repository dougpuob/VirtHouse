import { useState } from "react";
import { Alert, Button, Space, Typography } from "antd";

const { Paragraph, Text, Title } = Typography;

function clockLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function detailOf(body) {
  return body && typeof body.detail === "string" ? body.detail : "";
}

export default function PackRun({ run, onRefresh }) {
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const live = run.status === "running";

  async function stop() {
    setSending(true);
    try {
      const response = await fetch(`/api/v1/builds/${run.id}/cancel`, { method: "POST" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setNote(detailOf(payload) || "Packer did not stop.");
        return;
      }
      setNote("");
      onRefresh?.();
    } finally {
      setSending(false);
    }
  }

  return (
    <div>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }} align="start">
        <div>
          <Title level={5} style={{ margin: 0 }}>{run.name}</Title>
          <Text type="secondary">{run.status === "running" ? "Packing" : run.status === "done" ? "Finished" : run.status === "cancelled" ? "Stopped" : "Failed"}</Text>
        </div>
        <Button danger disabled={!live || sending} onClick={stop}>Stop</Button>
      </Space>
      <Paragraph>
        Packer does not open a window on this computer. It types the boot command on a display, and this page shows that display without sending keys. A screenshot is kept each time the picture changes.
      </Paragraph>
      {run.error ? <Alert type="error" showIcon style={{ marginBottom: 12 }} message={run.error} /> : null}
      {note ? <Alert type="error" showIcon style={{ marginBottom: 12 }} message={note} /> : null}
      {run.vnc_port ? (
        <iframe
          title={run.label || "Current display"}
          src={`/ui/vnc.html?build=${encodeURIComponent(run.id)}`}
          style={{ display: "block", width: "100%", height: 460, border: 0, background: "#111" }}
        />
      ) : live || !run.frame ? (
        <div style={{ background: "#111", minHeight: 220, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Text style={{ color: "#bbb", padding: 24 }}>
            {live ? "Packer has not opened the display yet." : "This pack has no display frames."}
          </Text>
        </div>
      ) : null}
      {run.label ? <Paragraph style={{ marginTop: 8, marginBottom: 16 }}>{run.label}</Paragraph> : null}
      {!run.vnc_port && !run.frame && run.log.length ? (
        <pre style={{ margin: "0 0 16px", padding: 12, background: "#1e1e1e", color: "#e8e8e8", overflow: "auto", maxHeight: 220, font: "12px/1.45 ui-monospace, monospace" }}>
          {run.log.join("\n")}
        </pre>
      ) : null}
      <Title level={5}>This pack</Title>
      <Paragraph type="secondary">
        {run.shots.length
          ? "Every screenshot kept from the moment the display opened."
          : "Screenshots appear here as the installer moves."}
      </Paragraph>
      {run.shots.map((shot) => (
        <figure key={shot.id} style={{ margin: "0 0 16px" }}>
          <figcaption style={{ marginBottom: 4 }}>
            <Text type="secondary">{clockLabel(shot.at)} · {shot.label}</Text>
          </figcaption>
          <img
            alt={shot.label}
            src={`/api/v1/builds/${run.id}/screen/${shot.id}.png`}
            style={{ display: "block", width: "100%", maxHeight: 320, objectFit: "contain", background: "#111" }}
          />
        </figure>
      ))}
      {run.status === "done" ? (
        <Paragraph>The disk is in {run.output_directory}.</Paragraph>
      ) : null}
    </div>
  );
}
