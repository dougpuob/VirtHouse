import { useState } from "react";
import { Alert, Button, Card, Checkbox, Descriptions, Input, List, Select, Space, Table, Typography } from "antd";
import { checksumReady, commitIso, formatBytes, isoRecords, mediaOf } from "./iso.js";
import { isoPath } from "./packer.js";
import { blankDraft } from "./packer.js";
import { defaultPassName, ensurePassDesigns, guestAttach, savePass, slotOk, usbPlace } from "./pass.js";

const { Paragraph, Text, Title } = Typography;

export default function Resource({ mode, config, shelf, onOpen, onTemplate }) {
  const [savedIso, setSavedIso] = useState(isoRecords);
  const [selectedIso, setSelectedIso] = useState(shelf.isos[0] ? shelf.isos[0].name : null);
  const [designs, setDesigns] = useState(() => ensurePassDesigns(shelf.devices));
  const iso = shelf.isos.find((item) => item.name === selectedIso) || shelf.isos[0];
  const media = iso ? mediaOf(iso, savedIso) : null;

  function patchIso(patch) {
    if (!iso) return;
    setSavedIso(commitIso(iso.name, patch));
  }

  if (mode === "resource") {
    const allowed = shelf.devices.filter((device) => designs[device.id] && designs[device.id].allowed).length;
    return (
      <div>
        <Title level={4} style={{ marginTop: 0 }}>Resource</Title>
        <Paragraph>ISO image and pass-through device each have their own page for choosing and setting that resource.</Paragraph>
        <Table
          pagination={false}
          rowKey="key"
          dataSource={[
            { key: "iso", page: "ISO image", count: shelf.isos.length, detail: "Install discs" },
            { key: "passthrough", page: "Pass-through device", count: shelf.devices.length, detail: `${allowed} a guest can take` },
          ]}
          columns={[
            { title: "Page", dataIndex: "page", render: (label, row) => <Button type="link" style={{ padding: 0 }} onClick={() => onOpen(row.key)}>{label}</Button> },
            { title: "Count", dataIndex: "count" },
            { title: "Detail", dataIndex: "detail" },
          ]}
        />
      </div>
    );
  }

  if (mode === "iso") {
    return (
      <div>
        <Title level={4} style={{ marginTop: 0 }}>ISO image</Title>
        <Paragraph>Packer boots this disc. The file is iso_url. Checksum and firmware belong to the disc, and a new template in Creating copies them.</Paragraph>
        <div style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
          <Card title="Library" size="small">
            <List
              dataSource={shelf.isos}
              locale={{ emptyText: "No discs are in the ISO directory." }}
              renderItem={(item) => {
                const info = mediaOf(item, savedIso);
                return (
                  <List.Item style={{ cursor: "pointer", background: iso && iso.name === item.name ? "#e6f4ff" : undefined }} onClick={() => setSelectedIso(item.name)}>
                    <List.Item.Meta title={info.title} description={`${item.name} · ${formatBytes(item.bytes)}`} />
                  </List.Item>
                );
              }}
            />
          </Card>
          <Card title="Settings" size="small">
            {iso && media ? (
              <Space direction="vertical" style={{ width: "100%" }} size="middle">
                <div>
                  <Text type="secondary">Name</Text>
                  <Input value={media.title} onChange={(event) => patchIso({ title: event.target.value })} />
                  <Text type="secondary">Library label. The file name is what Packer uses as iso_url.</Text>
                </div>
                <Descriptions size="small" column={1} items={[
                  { key: "file", label: "File", children: iso.name },
                  { key: "size", label: "Size", children: formatBytes(iso.bytes) },
                  { key: "url", label: "iso_url", children: isoPath(config, iso.name) },
                  ...(media.arch ? [{ key: "arch", label: "Architecture", children: media.arch }] : []),
                  ...(media.edition ? [{ key: "edition", label: "Edition", children: media.edition }] : []),
                ]} />
                <div>
                  <Text type="secondary">iso_checksum</Text>
                  <Input
                    value={media.checksum}
                    placeholder="sha256:…"
                    status={checksumReady(media.checksum) ? "" : "warning"}
                    onChange={(event) => patchIso({ checksum: event.target.value })}
                  />
                  {checksumReady(media.checksum) ? null : <Alert style={{ marginTop: 8 }} type="warning" showIcon message="Packer refuses this disc until iso_checksum is sha256:… or file:…" />}
                </div>
                <div>
                  <Text type="secondary">Firmware</Text>
                  <Select
                    style={{ width: "100%" }}
                    value={media.firmware}
                    onChange={(value) => patchIso({ firmware: value })}
                    options={[{ value: "bios", label: "BIOS" }, { value: "uefi", label: "UEFI" }]}
                  />
                </div>
                <div>
                  <Text type="secondary">OS</Text>
                  <Select
                    style={{ width: "100%" }}
                    value={media.os}
                    onChange={(value) => patchIso({ os: value })}
                    options={["Ubuntu", "Debian", "Fedora", "Windows", "Other"].map((value) => ({ value, label: value }))}
                  />
                  <Text type="secondary">A new template uses ssh for Linux and winrm for Windows.</Text>
                </div>
                <Button
                  type="primary"
                  onClick={() => {
                    const next = blankDraft();
                    next.iso = iso.name;
                    next.iso_checksum = media.checksum;
                    next.firmware = media.firmware;
                    next.communicator = media.os === "Windows" ? "winrm" : "ssh";
                    next.name = media.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
                    next.vm_name = `${iso.name.replace(/\.iso$/i, "")}.qcow2`;
                    onTemplate(next);
                  }}
                >
                  New template
                </Button>
              </Space>
            ) : <Text type="secondary">Select an ISO file.</Text>}
          </Card>
        </div>
      </div>
    );
  }

  const saved = designs;
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>Pass-through device</Title>
      <Paragraph>Each row is a device on this host. Allow it, then set the name a guest uses and what that guest receives. Until you allow it, the device stays on the host and no guest can take it. One guest holds an allowed device at a time.</Paragraph>
      <Table
        size="small"
        pagination={false}
        rowKey="id"
        dataSource={shelf.devices}
        locale={{ emptyText: "No devices are listed." }}
        columns={[
          {
            title: "Allow",
            width: 72,
            render: (_, device) => (
              <Checkbox
                checked={Boolean(saved[device.id] && saved[device.id].allowed)}
                onChange={(event) => {
                  if (!event.target.checked) {
                    setDesigns(savePass(device.id, { allowed: false }));
                    return;
                  }
                  const current = saved[device.id] || {};
                  const patch = { allowed: true, restore: current.restore !== false };
                  if (typeof current.name !== "string" || !current.name.trim()) patch.name = defaultPassName(device);
                  if (device.kind === "pci" && !String(current.guestSlot || "").trim()) {
                    const used = new Set();
                    for (const other of shelf.devices) {
                      const item = saved[other.id];
                      if (other.id !== device.id && item && item.allowed && item.guestSlot) used.add(String(item.guestSlot).toLowerCase());
                    }
                    for (let slot = 6; slot < 32; slot += 1) {
                      const text = `${slot.toString(16).padStart(2, "0")}.0`;
                      if (!used.has(text)) {
                        patch.guestSlot = text;
                        break;
                      }
                    }
                  }
                  setDesigns(savePass(device.id, patch));
                }}
              />
            ),
          },
          {
            title: "Name",
            width: 200,
            render: (_, device) => {
              const item = saved[device.id] || {};
              const allowed = Boolean(item.allowed);
              return (
                <Space direction="vertical" size={2}>
                  <Input
                    disabled={!allowed}
                    value={typeof item.name === "string" ? item.name : ""}
                    placeholder="Name a guest uses"
                    onChange={(event) => setDesigns(savePass(device.id, { name: event.target.value }))}
                  />
                  {allowed && !(item.name || "").trim() ? <Text type="danger">A guest requests this device by this name.</Text> : null}
                </Space>
              );
            },
          },
          {
            title: "On this host",
            render: (_, device) => {
              const place = device.kind === "usb" ? usbPlace(device) : null;
              const mates = shelf.devices.filter((other) => other.id !== device.id && device.iommu_group != null && other.iommu_group === device.iommu_group);
              return (
                <Space direction="vertical" size={0}>
                  <Text strong>{device.name}</Text>
                  <Text type="secondary">{place ? `Bus ${place.bus}, port ${place.port}` : device.id}</Text>
                  <Text type="secondary">{device.driver ? `Host driver ${device.driver}` : "No host driver"}</Text>
                  {device.iommu_group != null ? <Text type="secondary">{mates.length ? `IOMMU group ${device.iommu_group} also has ${mates.map((other) => other.id).join(", ")}.` : `IOMMU group ${device.iommu_group} contains only this device.`}</Text> : null}
                  {device.host_input ? <Text type="danger">This keyboard is attached to the host. A guest that takes it uses this keyboard.</Text> : null}
                </Space>
              );
            },
          },
          {
            title: "Guest receives",
            render: (_, device) => {
              const item = saved[device.id] || {};
              if (!item.allowed) return "—";
              const attach = guestAttach(device, item, shelf.devices, saved);
              return (
                <Space direction="vertical" size={4}>
                  <Text code>{attach || "The guest attachment is not set."}</Text>
                  {device.kind === "pci" ? (
                    <Space>
                      <Text type="secondary">Guest PCI slot</Text>
                      <Input
                        style={{ width: 72 }}
                        value={item.guestSlot || ""}
                        onChange={(event) => setDesigns(savePass(device.id, { guestSlot: event.target.value }))}
                      />
                    </Space>
                  ) : null}
                  {device.kind === "pci" && !slotOk(item.guestSlot) ? <Text type="danger">Use a slot like 06.0.</Text> : null}
                  {device.kind === "pci" && slotOk(item.guestSlot) && !attach ? <Text type="danger">Guest slot {String(item.guestSlot).trim().toLowerCase()} is already used.</Text> : null}
                  <Checkbox
                    checked={item.restore !== false}
                    onChange={(event) => setDesigns(savePass(device.id, { restore: event.checked }))}
                  >
                    {item.restore !== false ? `When the guest stops, give it back to ${device.driver || "the host"}.` : "When the guest stops, leave it off the host driver."}
                  </Checkbox>
                </Space>
              );
            },
          },
          {
            title: "Can a guest take it",
            width: 160,
            render: (_, device) => {
              const allowed = Boolean(saved[device.id] && saved[device.id].allowed);
              return (
                <Space direction="vertical" size={0}>
                  <Text strong>{allowed ? "Yes" : "No"}</Text>
                  <Text type="secondary">{allowed ? "No guest holds it." : "It stays on the host."}</Text>
                </Space>
              );
            },
          },
        ]}
      />
    </div>
  );
}
