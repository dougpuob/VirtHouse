import { useEffect, useState } from "react";
import { Alert, Checkbox, Descriptions, Input, Menu, Table, Typography } from "antd";

const { Paragraph, Text, Title } = Typography;
const LEVELS = ["error", "warning", "information"];

function clock(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function placement(entry, view) {
  const places = [];
  if (entry.current) places.push("Current");
  if (entry.local_date === view.today) places.push("Today");
  else if (entry.local_date === view.yesterday) places.push("Yesterday");
  else {
    const scope = (view.scopes || []).find((item) => item.id === entry.local_date);
    places.push(scope ? scope.label : entry.local_date);
  }
  return places.length ? `Listed in ${places.join(" and ")}.` : "";
}

function levelText(level) {
  if (level === "error") return <Text type="danger">{level}</Text>;
  if (level === "warning") return <Text type="warning">{level}</Text>;
  return <Text type="secondary">{level}</Text>;
}

export default function HistoryPage() {
  const [scope, setScope] = useState("current");
  const [levels, setLevels] = useState(LEVELS);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [view, setView] = useState(null);
  const [failed, setFailed] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    const handle = setTimeout(() => setAppliedQuery(query.trim()), 200);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    let stop = false;
    async function load() {
      const params = new URLSearchParams();
      params.set("scope", scope);
      for (const level of levels) params.append("level", level);
      if (appliedQuery) params.set("q", appliedQuery);
      try {
        const response = await fetch(`/api/v1/history?${params.toString()}`);
        if (stop) return;
        if (!response.ok) {
          setFailed(true);
          return;
        }
        setFailed(false);
        setView(await response.json());
      } catch (_err) {
        if (!stop) setFailed(true);
      }
    }
    load();
    const timer = setInterval(load, 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [scope, levels, appliedQuery]);

  const entries = levels.length && view && !failed ? view.entries : [];
  const selected = entries.find((entry) => entry.id === selectedId) || null;
  const scopeLabel = view && view.scopes ? (view.scopes.find((item) => item.id === scope) || {}).label : "";

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", background: "#fff" }}>
      <div style={{ width: 168, flex: "none", borderRight: "1px solid #f0f0f0", overflow: "auto" }}>
        <Menu
          mode="inline"
          style={{ borderInlineEnd: 0 }}
          selectedKeys={[scope]}
          items={(view && view.scopes ? view.scopes : [
            { id: "current", label: "Current", count: 0 },
            { id: "today", label: "Today", count: 0 },
            { id: "yesterday", label: "Yesterday", count: 0 },
          ]).map((item) => ({
            key: item.id,
            label: (
              <span style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>{item.label}</span>
                <Text type="secondary">{item.count}</Text>
              </span>
            ),
          }))}
          onClick={({ key }) => {
            setScope(key);
            setSelectedId(null);
          }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "16px 16px 8px" }}>
          <Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>History</Title>
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {scopeLabel ? `${entries.length} shown in ${scopeLabel}. ` : ""}
            Current keeps this boot and today's errors. Today and Yesterday follow this host's calendar.
          </Paragraph>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
            <Checkbox.Group
              value={levels}
              onChange={(next) => {
                setLevels(next);
                setSelectedId(null);
              }}
              options={LEVELS.map((level) => ({
                label: `${level} ${view && view.levels ? view.levels[level] || 0 : 0}`,
                value: level,
              }))}
            />
            <Input
              allowClear
              placeholder="Search message, subject, action"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              style={{ width: 280 }}
            />
          </div>
        </div>
        {failed ? <Alert style={{ margin: 16 }} type="error" showIcon message="History is not available." /> : null}
        {view && view.truncated ? <Alert style={{ margin: "0 16px 8px" }} type="info" showIcon message="Showing the latest 500 rows in this scope." /> : null}
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 8px" }}>
          <Table
            size="small"
            pagination={false}
            rowKey="id"
            dataSource={entries}
            locale={{ emptyText: view ? "Nothing in this scope matches these levels and this search." : "Loading history…" }}
            onRow={(record) => ({
              onClick: () => setSelectedId((current) => (current === record.id ? null : record.id)),
              style: {
                cursor: "pointer",
                background: record.id === selectedId ? "#fff7e6" : undefined,
              },
            })}
            columns={[
              { title: "Time", dataIndex: "at", width: 88, render: clock },
              { title: "Level", dataIndex: "level", width: 120, render: levelText },
              { title: "Action", dataIndex: "action", width: 120 },
              {
                title: "Subject",
                dataIndex: "subject_name",
                width: 160,
                ellipsis: true,
                render: (value) => value || "—",
              },
              { title: "Message", dataIndex: "message", ellipsis: true },
            ]}
          />
        </div>
        {selected ? (
          <div style={{ flex: "none", borderTop: "1px solid #f0f0f0", padding: "12px 16px", maxHeight: "34%", overflow: "auto" }}>
            <Text strong>{selected.message}</Text>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>{placement(selected, view)}</Paragraph>
            <Descriptions
              size="small"
              column={1}
              items={[
                ["When", when(selected.at)],
                ["Level", selected.level],
                ["Action", selected.action],
                ["Subject", selected.subject_name || "—"],
                ...(selected.subject_id ? [["Id", selected.subject_id]] : []),
                ...Object.entries(selected.detail || {}).map(([key, value]) => [
                  key.replace(/_/g, " "),
                  value == null || value === "" ? "—" : String(value),
                ]),
              ].map(([label, children]) => ({ key: label, label, children }))}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
