import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Descriptions, Form, Input, List, Select, Space, Table, Typography } from "antd";
import { mediaOf } from "./iso.js";
import { blankDraft, finishedBuild, loadDrafts, newId, packerGaps, packerHcl, saveDrafts, workDirectory } from "./packer.js";
import PackRun from "./PackRun.jsx";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

function field(label, extra, control) {
  return (
    <Form.Item label={label} extra={extra} style={{ marginBottom: 12 }}>
      {control}
    </Form.Item>
  );
}

export default function Builder({ mode, config, catalog, shelf, seed, onOpen, onMenuRefresh, onSeedConsumed }) {
  const [drafts, setDrafts] = useState(loadDrafts);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(blankDraft);
  const [pickedBuild, setPickedBuild] = useState(null);
  const [pickedImage, setPickedImage] = useState(catalog.images[0] ? catalog.images[0].name : null);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [starting, setStarting] = useState(false);
  const [runNote, setRunNote] = useState("");
  const [runTick, setRunTick] = useState(0);
  const pinned = useRef(false);

  useEffect(() => {
    if (!seed) return;
    pinned.current = true;
    setRunId(null);
    setPickedBuild(null);
    setSelectedId(seed.id || null);
    setDraft({
      ...blankDraft(),
      ...seed,
      id: seed.id || newId(),
      provisioners: Array.isArray(seed.provisioners) ? seed.provisioners : [],
    });
    onSeedConsumed?.();
  }, [seed]);

  useEffect(() => {
    if (mode !== "creating") return undefined;
    let stop = false;
    async function poll() {
      try {
        const response = await fetch("/api/v1/builds");
        if (!response.ok || stop) return;
        const body = await response.json();
        if (!stop) setRuns(Array.isArray(body) ? body : []);
      } catch (_err) {
        if (!stop) setRuns([]);
      }
    }
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [mode, runTick]);

  useEffect(() => {
    if (pinned.current || runId || pickedBuild) return;
    const live = runs.find((item) => item.status === "running");
    if (live) setRunId(live.id);
  }, [runs, runId, pickedBuild]);

  function persist(nextDrafts, id) {
    setDrafts(nextDrafts);
    saveDrafts(nextDrafts);
    onMenuRefresh();
    if (id) setSelectedId(id);
  }

  function update(patch) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function chooseIso(name) {
    const item = shelf.isos.find((entry) => entry.name === name);
    const patch = { iso: name };
    if (item) {
      const media = mediaOf(item);
      if (!draft.iso_checksum.trim() && media.checksum) patch.iso_checksum = media.checksum;
      patch.firmware = media.firmware;
      patch.communicator = media.os === "Windows" ? "winrm" : "ssh";
      if (!draft.vm_name.trim()) patch.vm_name = `${item.name.replace(/\.iso$/i, "")}.qcow2`;
    }
    update(patch);
  }

  const hcl = useMemo(() => packerHcl(config, draft), [config, draft]);
  const gaps = packerGaps(draft);
  const done = catalog.builds.filter(finishedBuild);
  const image = catalog.images.find((item) => item.name === pickedImage);
  const build = done.find((item) => item.name === pickedBuild);

  if (mode === "builder") {
    return (
      <div>
        <Title level={4} style={{ marginTop: 0 }}>Builder</Title>
        <Paragraph>Builder runs Packer with the QEMU plugin. Creating is where you set the template and run it. Packer starts its own QEMU and types on that display. Creating keeps a screenshot each time the picture changes. That QEMU is not a machine. The qcow2 is written under the work directory, then listed in Dump.</Paragraph>
        <Table
          pagination={false}
          rowKey="key"
          dataSource={[
            { key: "creating", page: "Creating", holds: "The template, then the running pack and screenshots of its display" },
            { key: "dump", page: "Dump", holds: "The qcow2 Packer wrote, and images a machine can already start from" },
          ]}
          columns={[
            { title: "Page", dataIndex: "page", render: (label, row) => <Button type="link" style={{ padding: 0 }} onClick={() => onOpen(row.key)}>{label}</Button> },
            { title: "Holds", dataIndex: "holds" },
          ]}
        />
      </div>
    );
  }

  if (mode === "dump") {
    return (
      <div>
        <Title level={4} style={{ marginTop: 0 }}>Dump</Title>
        <Paragraph>Packer writes the qcow2 into that build's output directory under work. A machine does not boot that file directly. Promoting it into bases records a usable image, and a later start creates an overlay.</Paragraph>
        <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0, 1fr)", gap: 16 }}>
          <Card title="Disks" size="small">
            <List
              dataSource={[...catalog.images.map((item) => ({ kind: "image", ...item })), ...done.map((item) => ({ kind: "build", ...item }))]}
              locale={{ emptyText: "No finished disk is recorded." }}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: "pointer", background: (item.kind === "image" ? pickedImage === item.name && !pickedBuild : pickedBuild === item.name) ? "#e6f4ff" : undefined }}
                  onClick={() => {
                    if (item.kind === "image") {
                      setPickedImage(item.name);
                      setPickedBuild(null);
                    } else {
                      setPickedBuild(item.name);
                      setPickedImage(null);
                    }
                  }}
                >
                  <List.Item.Meta title={item.name} description={item.status} />
                </List.Item>
              )}
            />
          </Card>
          <Card title={image && !pickedBuild ? image.name : build ? build.name : "Disk"} size="small">
            {image && !pickedBuild ? (
              <>
                <Descriptions column={1} size="small" items={[
                  { key: "file", label: "File", children: image.file },
                  { key: "status", label: "Status", children: image.status },
                  { key: "dir", label: "Directory", children: config && config.paths ? config.paths.bases : "—" },
                  { key: "use", label: "Use", children: "A machine starts from a new overlay of this file." },
                ]} />
                <Paragraph type="secondary" style={{ marginTop: 12 }}>images.yaml has the name, file, and status. It does not store a Packer manifest for this disk.</Paragraph>
              </>
            ) : null}
            {build ? (
              <>
                <Descriptions column={1} size="small" items={[
                  { key: "status", label: "Status", children: build.status },
                  { key: "out", label: "output_directory", children: workDirectory(config, build.name) },
                ]} />
                <Paragraph type="secondary" style={{ marginTop: 12 }}>Promoting this file into bases is not available from this page yet.</Paragraph>
              </>
            ) : null}
            {!image && !build ? <Text type="secondary">Select a disk.</Text> : null}
          </Card>
        </div>
      </div>
    );
  }

  const recorded = catalog.builds.find((item) => item.name === pickedBuild && !finishedBuild(item));
  const run = runs.find((item) => item.id === runId) || null;
  const packing = runs.some((item) => item.status === "running");
  async function runPack() {
    if (!draft.name.trim() || gaps.length || packing) return;
    setStarting(true);
    setRunNote("");
    const next = drafts.some((item) => item.id === draft.id)
      ? drafts.map((item) => (item.id === draft.id ? draft : item))
      : [...drafts, draft];
    persist(next, draft.id);
    try {
      const response = await fetch("/api/v1/builds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: draft.name.trim(), hcl }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setRunNote(typeof body.detail === "string" ? body.detail : "Packer did not start.");
        return;
      }
      pinned.current = true;
      setPickedBuild(null);
      setRunId(body.id);
      setRunTick((value) => value + 1);
    } catch (_err) {
      setRunNote("Packer did not start.");
    } finally {
      setStarting(false);
    }
  }
  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>Creating</Title>
      <Paragraph>Set the template, then run it. Packer starts its own QEMU and types the boot command on that display. This page shows that display and does not send keys. Each change is kept as a screenshot. The disk Packer writes shows up in Dump.</Paragraph>
      <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <div>
          {runs.length ? (
            <Card title="Packs" size="small" style={{ marginBottom: 16 }}>
              <List
                dataSource={runs}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: "pointer", background: runId === item.id ? "#e6f4ff" : undefined }}
                    onClick={() => {
                      pinned.current = true;
                      setPickedBuild(null);
                      setRunId(item.id);
                    }}
                  >
                    <List.Item.Meta title={item.name} description={item.status === "running" ? "packing" : item.status} />
                  </List.Item>
                )}
              />
            </Card>
          ) : null}
          <Card title="Templates" size="small">
            <List
              dataSource={[{ id: "", name: "New template" }, ...drafts, ...catalog.builds.filter((item) => !finishedBuild(item)).map((item) => ({ ...item, recorded: true }))]}
              renderItem={(item) => {
                const active = !runId && (item.recorded ? pickedBuild === item.name : item.id ? selectedId === item.id && !pickedBuild : !selectedId && !pickedBuild);
                return (
                  <List.Item
                    style={{ cursor: "pointer", background: active ? "#e6f4ff" : undefined }}
                    onClick={() => {
                      pinned.current = true;
                      setRunId(null);
                      setRunNote("");
                      if (item.recorded) {
                        setPickedBuild(item.name);
                        return;
                      }
                      setPickedBuild(null);
                      if (!item.id) {
                        setSelectedId(null);
                        setDraft(blankDraft());
                        return;
                      }
                      setSelectedId(item.id);
                      setDraft(drafts.find((entry) => entry.id === item.id) || blankDraft());
                    }}
                  >
                    <List.Item.Meta title={item.name || "Untitled"} description={item.recorded ? item.status : null} />
                  </List.Item>
                );
              }}
            />
          </Card>
        </div>
        <Card title={run ? run.name : recorded ? recorded.name : (draft.name.trim() || "New template")} size="small">
          {run ? (
            <PackRun run={run} onRefresh={() => setRunTick((value) => value + 1)} />
          ) : recorded ? (
            <>
              <Descriptions column={1} size="small" items={[{ key: "status", label: "Status", children: recorded.status }]} />
              <Paragraph type="secondary">images.yaml only records the name and status. The Packer template for this build is not stored.</Paragraph>
            </>
          ) : (
            <Form layout="horizontal" labelCol={{ flex: "168px" }} wrapperCol={{ flex: "1 1 280px" }} labelWrap>
              <Paragraph>Packer installs from the ISO, then writes one qcow2. Run starts that QEMU and opens its display on this page. It is not listed under Machines.</Paragraph>
              <Space wrap style={{ marginBottom: 12 }}>
                <Button
                  onClick={() => {
                    if (!draft.name.trim()) return;
                    const next = drafts.some((item) => item.id === draft.id)
                      ? drafts.map((item) => (item.id === draft.id ? draft : item))
                      : [...drafts, draft];
                    persist(next, draft.id);
                  }}
                >
                  Save
                </Button>
                <Button type="primary" disabled={Boolean(gaps.length) || packing} loading={starting} onClick={runPack}>Run</Button>
                {drafts.some((item) => item.id === draft.id) ? (
                  <Button
                    danger
                    onClick={() => {
                      persist(drafts.filter((item) => item.id !== draft.id));
                      setSelectedId(null);
                      setDraft(blankDraft());
                    }}
                  >
                    Delete
                  </Button>
                ) : null}
                {packing ? <Text type="secondary">A pack is already running.</Text> : null}
              </Space>
              {runNote ? <Alert type="error" showIcon style={{ marginBottom: 12 }} message={runNote} /> : null}
              {gaps.length ? <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`Packer still needs ${gaps.join(", ")}.`} /> : null}
              <Title level={5}>Source</Title>
              <Paragraph type="secondary">iso_url and iso_checksum are required. format stays qcow2 and accelerator stays kvm. output_directory must be empty or absent when Packer starts.</Paragraph>
              {field("name", "Recorded in images.yaml when a build exists. This draft stays in the browser until then.", <Input value={draft.name} onChange={(event) => update({ name: event.target.value })} />)}
              {field("output_directory", null, <Input readOnly value={workDirectory(config, draft.name)} />)}
              {field("iso_url", "Chosen from the ISO directory. Checksum and firmware come from that disc when this template has not set them.", (
                <Select
                  value={draft.iso || undefined}
                  placeholder="Select an ISO"
                  onChange={chooseIso}
                  options={shelf.isos.map((item) => {
                    const media = mediaOf(item);
                    return { value: item.name, label: media.title && media.title !== item.name ? media.title : item.name };
                  })}
                />
              ))}
              {field("iso_checksum", "Required. sha256: and the digest, or file: and a checksum file.", <Input value={draft.iso_checksum} onChange={(event) => update({ iso_checksum: event.target.value })} />)}
              {field("vm_name", "Packer does not add a file extension. Include .qcow2.", <Input value={draft.vm_name} onChange={(event) => update({ vm_name: event.target.value })} />)}
              {field("disk_size", "Packer's own default is 40960M.", <Input value={draft.disk_size} onChange={(event) => update({ disk_size: event.target.value })} />)}
              {field("machine_type", "Packer's own default is pc.", <Input value={draft.machine_type} onChange={(event) => update({ machine_type: event.target.value })} />)}
              {field("cpus", null, <Input value={draft.cpus} onChange={(event) => update({ cpus: event.target.value })} />)}
              {field("memory", "Megabytes.", <Input value={draft.memory} onChange={(event) => update({ memory: event.target.value })} />)}
              {field("firmware", null, (
                <Select
                  value={draft.firmware}
                  onChange={(value) => update({ firmware: value })}
                  options={[{ value: "bios", label: "BIOS" }, { value: "uefi", label: "UEFI" }]}
                />
              ))}
              {draft.firmware === "uefi" ? field("efi_firmware_code", "Host path to OVMF_CODE. Required when efi_boot is true.", <Input value={draft.efi_code} onChange={(event) => update({ efi_code: event.target.value })} />) : null}
              {draft.firmware === "uefi" ? field("efi_firmware_vars", null, <Input value={draft.efi_vars} onChange={(event) => update({ efi_vars: event.target.value })} />) : null}
              <Descriptions
                size="small"
                column={1}
                items={[
                  { key: "plugin", label: "Plugin", children: "github.com/hashicorp/qemu" },
                  { key: "format", label: "format", children: "qcow2" },
                  { key: "accel", label: "accelerator", children: "kvm" },
                  { key: "disk", label: "disk_interface", children: "virtio" },
                  { key: "net", label: "net_device", children: "virtio-net" },
                  { key: "head", label: "headless", children: "true" },
                ]}
              />
              <Title level={5}>Boot</Title>
              <Paragraph type="secondary">boot_command is what Packer types on the temporary console. http_content is the installer seed. The boot command has to point the installer at {"{{ .HTTPIP }}:{{ .HTTPPort }}"}.</Paragraph>
              {field("boot_wait", null, <Input value={draft.boot_wait} onChange={(event) => update({ boot_wait: event.target.value })} />)}
              {field("boot_command", "One line per command. Packer sends these over VNC.", <TextArea autoSize={{ minRows: 3 }} value={draft.boot_command} onChange={(event) => update({ boot_command: event.target.value })} />)}
              {field("/user-data", "Ubuntu autoinstall or a kickstart file. Served as http_content.", <TextArea autoSize={{ minRows: 3 }} value={draft.user_data} onChange={(event) => update({ user_data: event.target.value })} />)}
              {field("/meta-data", null, <TextArea autoSize={{ minRows: 2 }} value={draft.meta_data} onChange={(event) => update({ meta_data: event.target.value })} />)}
              <Title level={5}>Communicator</Title>
              <Paragraph type="secondary">Packer connects after install and runs provisioners. ssh_username is required for SSH. winrm_username is required for WinRM. none means no provisioners.</Paragraph>
              {field("communicator", null, (
                <Select
                  value={draft.communicator}
                  onChange={(value) => update({ communicator: value })}
                  options={["ssh", "winrm", "none"].map((value) => ({ value, label: value }))}
                />
              ))}
              {draft.communicator !== "none" ? field(draft.communicator === "winrm" ? "winrm_username" : "ssh_username", null, <Input value={draft.username} onChange={(event) => update({ username: event.target.value })} />) : null}
              {draft.communicator !== "none" ? field(draft.communicator === "winrm" ? "winrm_password" : "ssh_password", null, <Input value={draft.password} onChange={(event) => update({ password: event.target.value })} />) : null}
              {draft.communicator !== "none" ? field(draft.communicator === "winrm" ? "winrm_timeout" : "ssh_timeout", "Packer's SSH default is 5m.", <Input value={draft.timeout} onChange={(event) => update({ timeout: event.target.value })} />) : null}
              <Title level={5}>Shutdown</Title>
              <Paragraph type="secondary">An empty shutdown_command makes Packer power the guest off. shutdown_timeout defaults to 5m.</Paragraph>
              {field("shutdown_command", null, <Input value={draft.shutdown_command} onChange={(event) => update({ shutdown_command: event.target.value })} />)}
              {field("shutdown_timeout", null, <Input value={draft.shutdown_timeout} onChange={(event) => update({ shutdown_timeout: event.target.value })} />)}
              <Title level={5}>Provisioners</Title>
              {draft.provisioners.length === 0 ? <Paragraph type="secondary">No provisioners. Packer shuts the guest down after the communicator connects.</Paragraph> : null}
              {draft.provisioners.map((item, index) => (
                <Card key={index} size="small" style={{ marginBottom: 8 }} title={item.type === "file" ? "file" : "shell"} extra={<Button type="link" danger onClick={() => update({ provisioners: draft.provisioners.filter((_, at) => at !== index) })}>Remove</Button>}>
                  {item.type === "file" ? (
                    <>
                      {field("source", null, <Input value={item.source || ""} onChange={(event) => update({ provisioners: draft.provisioners.map((entry, at) => at === index ? { ...entry, source: event.target.value } : entry) })} />)}
                      {field("destination", null, <Input value={item.destination || ""} onChange={(event) => update({ provisioners: draft.provisioners.map((entry, at) => at === index ? { ...entry, destination: event.target.value } : entry) })} />)}
                    </>
                  ) : field("inline", "One shell command per line. Runs over SSH before shutdown.", <TextArea autoSize={{ minRows: 3 }} value={item.script || ""} onChange={(event) => update({ provisioners: draft.provisioners.map((entry, at) => at === index ? { ...entry, script: event.target.value } : entry) })} />)}
                </Card>
              ))}
              <Space style={{ marginBottom: 16 }}>
                <Button onClick={() => update({ provisioners: [...draft.provisioners, { type: "shell", script: "" }] })}>Add shell</Button>
                <Button onClick={() => update({ provisioners: [...draft.provisioners, { type: "file", source: "", destination: "" }] })}>Add file</Button>
              </Space>
              <Title level={5}>Template</Title>
              <Paragraph type="secondary">This is the file Run hands to Packer. The display Packer drives is shown with the pack, not in this template.</Paragraph>
              <pre style={{ margin: 0, padding: 12, background: "#1e1e1e", color: "#e8e8e8", overflow: "auto", maxHeight: 320, font: "12px/1.45 ui-monospace, monospace" }}>{hcl}</pre>
            </Form>
          )}
        </Card>
      </div>
    </div>
  );
}
