import { Alert, Button, Card, Col, Descriptions, Progress, Row, Statistic, Table, Typography } from "antd";

const { Paragraph, Title } = Typography;

function items(pairs) {
  return pairs.map(([label, children]) => ({
    key: label,
    label,
    children: children == null || children === "" ? "—" : String(children),
  }));
}

export function DashboardView({ host, vms, onOpenVm }) {
  if (!host) return <Alert type="warning" showIcon message="Host usage is not loaded." />;
  const running = vms.filter((vm) => ["pending", "starting", "booting", "ready"].includes(vm.status));
  const used = Math.max(0, host.memory_total_mb - host.memory_available_mb);
  const pct = host.memory_total_mb ? Math.round((used / host.memory_total_mb) * 100) : 0;
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>{host.hostname || "This host"}</Title>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}><Card><Statistic title="CPUs" value={host.cpu_count} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Load" value={host.load_1m} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Memory free" value={host.memory_available_mb} suffix="MB" /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="Running" value={running.length} suffix={`/ ${vms.length}`} /></Card></Col>
      </Row>
      <Card style={{ marginTop: 16 }} title="Memory">
        <Paragraph>Memory {used} MB used / {host.memory_total_mb} MB</Paragraph>
        <Progress percent={pct} />
      </Card>
      <Card style={{ marginTop: 16 }} title="Host">
        <Descriptions
          column={1}
          size="small"
          items={items([
            ["Host", location.hostname || host.hostname],
            ["Reserve memory", `${host.reserve_memory_mb} MB`],
            ["Reserve CPUs", host.reserve_cpus],
            ["QEMU", host.qemu_binary],
            ["First subnet", host.subnet_base],
          ])}
        />
      </Card>
      <Card style={{ marginTop: 16 }} title="Machines">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={vms}
          locale={{ emptyText: "No machines" }}
          columns={[
            { title: "Name", dataIndex: "name", render: (name, vm) => <Button type="link" style={{ padding: 0 }} onClick={() => onOpenVm(vm.id)}>{name}</Button> },
            { title: "Status", dataIndex: "status" },
            { title: "CPUs", dataIndex: "cpus" },
            { title: "Memory", dataIndex: "memory_mb", render: (value) => `${value} MB` },
            { title: "Guest", dataIndex: "guest_ip", render: (value) => value || "—" },
          ]}
        />
      </Card>
      <Card style={{ marginTop: 16 }} title="Daemons">
        <Table
          size="small"
          pagination={false}
          rowKey="pid"
          dataSource={host.processes || []}
          columns={[
            { title: "Process", dataIndex: "name" },
            { title: "PID", dataIndex: "pid" },
            { title: "RSS", dataIndex: "rss_mb", render: (value) => `${value} MB` },
            { title: "Threads", dataIndex: "threads", render: (value) => value ?? "—" },
          ]}
        />
      </Card>
    </div>
  );
}

export function SettingsView({ config }) {
  if (!config) return <Alert type="warning" showIcon message="System config is not loaded." />;
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>Settings</Title>
      <Paragraph type="secondary">Loaded from system.yaml. Saving changes is not available yet. Builds and usable images are recorded in images.yaml.</Paragraph>
      <Card title="Paths" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" items={items([["ISO", config.paths.isos], ["Base", config.paths.bases], ["Work", config.paths.work], ["Overlay", config.paths.overlays], ["QMP", config.paths.qmp], ["History", config.paths.history]])} />
      </Card>
      <Card title="Resources" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" items={items([["Reserve memory", `${config.resources.reserve_memory_mb} MB`], ["Reserve CPUs", config.resources.reserve_cpus], ["Max VM memory", config.resources.max_vm_memory_mb], ["Max VM CPUs", config.resources.max_vm_cpus]])} />
      </Card>
      <Card title="Network" style={{ marginBottom: 16 }}>
        <Descriptions column={1} size="small" items={items([["First subnet", config.network.subnet_base]])} />
      </Card>
      <Card title="Timeouts">
        <Descriptions column={1} size="small" items={items([
          ["Process start", `${config.timeouts.process_start_sec} s`],
          ["Basic ready", `${config.timeouts.basic_ready_sec} s`],
          ["Linux ready", `${config.timeouts.system_ready_linux_sec} s`],
          ["Windows ready", `${config.timeouts.system_ready_windows_sec} s`],
          ["Overall", `${config.timeouts.overall_sec} s`],
        ])} />
      </Card>
    </div>
  );
}
