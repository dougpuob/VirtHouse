import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, ConfigProvider, Layout, Menu, Typography, theme } from "antd";
import {
  BuildOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DesktopOutlined,
  HistoryOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import Machines from "./Machines.jsx";
import Builder from "./Builder.jsx";
import Resource from "./Resource.jsx";
import HistoryPage from "./History.jsx";
import { DashboardView, SettingsView } from "./Home.jsx";
import { finishedBuild, loadDrafts } from "./packer.js";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const SIDER_THEME = {
  components: {
    Layout: { lightSiderBg: "#d5dbe3" },
    Menu: {
      itemBg: "#d5dbe3",
      subMenuItemBg: "#eef1f5",
      itemHoverBg: "#c5ced8",
      itemActiveBg: "#b4c0cc",
      itemSelectedBg: "#8f5310",
      itemSelectedColor: "#ffffff",
    },
  },
};

const SIDER_MENU_CSS = `
.sider-menu.ant-menu-light .ant-menu-submenu-selected > .ant-menu-submenu-title {
  color: rgba(0, 0, 0, 0.88) !important;
}
`;

const SPEC = {
  name: "ubuntu2404",
  base_image: "ubuntu2404-q35.qcow2",
  cpus: 10,
  memory_mb: 8192,
  extra_qemu_args: ["-cpu", "host"],
};

const EMPTY = { vms: [], config: null, host: null, catalog: { builds: [], images: [] }, shelf: { isos: [], devices: [] }, packs: [], qmp: null, currentErrors: 0 };

export default function App() {
  const [data, setData] = useState(EMPTY);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("machines");
  const [selectedId, setSelectedId] = useState(null);
  const [openKeys, setOpenKeys] = useState(["machines-group"]);
  const [busy, setBusy] = useState("");
  const [summary, setSummary] = useState("");
  const [menuTick, setMenuTick] = useState(0);
  const [seed, setSeed] = useState(null);
  const picked = useRef(false);

  useEffect(() => {
    let stop = false;
    async function refresh() {
      try {
        const [vmResponse, configResponse, hostResponse, imageResponse, shelfResponse] = await Promise.all([
          fetch("/api/v1/vms"),
          fetch("/api/v1/config"),
          fetch("/api/v1/resources"),
          fetch("/api/v1/images"),
          fetch("/ui/resource.json"),
        ]);
        if (!vmResponse.ok) {
          if (!stop) setError("Cannot reach the VM API");
          return;
        }
        const vms = await vmResponse.json();
        const config = configResponse.ok ? await configResponse.json() : null;
        const host = hostResponse.ok ? await hostResponse.json() : null;
        let catalog = { builds: [], images: [] };
        if (imageResponse.ok) catalog = await imageResponse.json();
        else {
          const fallback = await fetch("/ui/images.json");
          if (fallback.ok) catalog = await fallback.json();
        }
        const shelf = shelfResponse.ok ? await shelfResponse.json() : { isos: [], devices: [] };
        let packs = [];
        try {
          const packResponse = await fetch("/api/v1/builds");
          if (packResponse.ok) {
            const body = await packResponse.json();
            if (Array.isArray(body)) packs = body;
          }
        } catch (_err) {
          packs = [];
        }
        let currentErrors = 0;
        try {
          const historyResponse = await fetch("/api/v1/history?scope=current");
          if (historyResponse.ok) {
            const history = await historyResponse.json();
            currentErrors = history.current_errors || 0;
          }
        } catch (_err) {
          currentErrors = 0;
        }
        let qmp = null;
        const current = vms.find((vm) => vm.id === selectedId);
        if (current && (current.status === "booting" || current.status === "ready")) {
          const qmpResponse = await fetch(`/api/v1/vms/${encodeURIComponent(current.id)}/qmp`);
          if (qmpResponse.ok) qmp = { id: current.id, ...(await qmpResponse.json()) };
          else {
            const body = await qmpResponse.json().catch(() => ({}));
            qmp = { id: current.id, error: body.detail || "QMP query failed" };
          }
        }
        if (stop) return;
        setError("");
        setData({ vms, config, host, catalog, shelf, packs, qmp, currentErrors });
        setSelectedId((id) => {
          if (id && vms.some((vm) => vm.id === id)) return id;
          if (id) return null;
          if (picked.current) return null;
          const running = vms.find((vm) => ["pending", "starting", "booting", "ready"].includes(vm.status));
          return running ? running.id : null;
        });
      } catch (_err) {
        if (!stop) setError("Cannot reach the VM API");
      }
    }
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [selectedId]);

  const vm = data.vms.find((item) => item.id === selectedId) || null;
  const running = data.vms.filter((item) => ["pending", "starting", "booting", "ready"].includes(item.status));
  const creatingCount = loadDrafts().length
    + data.catalog.builds.filter((build) => !finishedBuild(build)).length
    + data.packs.filter((pack) => pack.status === "running").length;
  const dumpCount = data.catalog.images.length + data.catalog.builds.filter(finishedBuild).length;
  void menuTick;

  const items = useMemo(() => [
    { key: "dashboard", icon: <DashboardOutlined />, label: "Dashboard" },
    {
      key: "machines-group",
      icon: <DesktopOutlined />,
      label: "Machines",
      children: [
        { key: "host", label: (data.host && data.host.hostname) || "This host" },
        ...data.vms.map((item) => ({ key: `vm:${item.id}`, label: `${item.name} · ${item.status}` })),
        ...(data.vms.length ? [] : [{ key: "no-machines", label: "No machines", disabled: true }]),
      ],
    },
    {
      key: "builder-group",
      icon: <BuildOutlined />,
      label: "Builder",
      children: [
        { key: "builder", label: "Overview" },
        { key: "creating", label: `Creating (${creatingCount})` },
        { key: "dump", label: `Dump (${dumpCount})` },
      ],
    },
    {
      key: "resource-group",
      icon: <DatabaseOutlined />,
      label: "Resource",
      children: [
        { key: "resource", label: "Overview" },
        { key: "iso", label: `ISO image (${data.shelf.isos.length})` },
        { key: "passthrough", label: `Pass-through device (${data.shelf.devices.length})` },
      ],
    },
    {
      key: "history",
      icon: <HistoryOutlined />,
      label: (
        <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
          <span>History</span>
          {data.currentErrors ? <span style={{ color: "#c0392b" }}>{data.currentErrors}</span> : null}
        </span>
      ),
    },
  ], [data, creatingCount, dumpCount]);

  const selectedKeys = mode === "machines" ? [selectedId ? `vm:${selectedId}` : "host"] : [mode];

  function openPage(next) {
    setMode(next);
    const group = next === "creating" || next === "dump" || next === "builder"
      ? "builder-group"
      : next === "iso" || next === "passthrough" || next === "resource"
        ? "resource-group"
        : null;
    if (group) setOpenKeys((keys) => (keys.includes(group) ? keys : [...keys, group]));
  }

  async function start() {
    setBusy("start");
    setSummary("Starting Ubuntu 24.04…");
    const response = await fetch("/api/v1/vms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(SPEC),
    });
    setBusy("");
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setSummary(body.detail || "Start failed");
      return;
    }
    const created = await response.json();
    setSelectedId(created.id);
    setMode("machines");
    setSummary("");
  }

  async function stop() {
    if (!vm) return;
    setBusy("stop");
    await fetch(`/api/v1/vms/${encodeURIComponent(vm.id)}`, { method: "DELETE" });
    setBusy("");
    setSelectedId(null);
  }

  async function reset() {
    if (!vm) return;
    setBusy("reset");
    const response = await fetch(`/api/v1/vms/${encodeURIComponent(vm.id)}/reset`, { method: "POST" });
    setBusy("");
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setSummary(body.detail || "Reset failed");
    }
  }

  const meta = data.host ? `${data.host.cpu_count} CPUs · ${data.host.memory_available_mb} MB free` : "";
  const pageSummary = mode === "machines"
    ? (vm ? `${vm.guest_ip || ""}` : `${running.length} running`)
    : summary;

  return (
    <ConfigProvider theme={{ algorithm: theme.compactAlgorithm, token: { colorPrimary: "#e08a1e", borderRadius: 6 } }}>
      <Layout style={{ height: "100vh" }}>
        <Header style={{ display: "flex", alignItems: "center", gap: 16, padding: "0 20px" }}>
          <Text style={{ color: "#fff", fontSize: 18, fontWeight: 600, margin: 0 }}>
            <span style={{ color: "#e08a1e" }}>Virt</span>House
          </Text>
          <Text style={{ color: "rgba(255,255,255,.65)" }}>{meta}</Text>
        </Header>
        <Layout style={{ flex: 1, minHeight: 0 }}>
          <ConfigProvider theme={SIDER_THEME}>
            <Sider width={248} theme="light" style={{ borderRight: "1px solid #c5ced6" }}>
              <style>{SIDER_MENU_CSS}</style>
              <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                <Menu
                  className="sider-menu"
                  mode="inline"
                  style={{ flex: 1, overflow: "auto", borderInlineEnd: 0 }}
                  items={items}
                  selectedKeys={selectedKeys}
                  openKeys={openKeys}
                  onOpenChange={setOpenKeys}
                  onClick={({ key }) => {
                    if (key === "host") {
                      picked.current = true;
                      setMode("machines");
                      setSelectedId(null);
                      return;
                    }
                    if (key.startsWith("vm:")) {
                      picked.current = true;
                      setMode("machines");
                      setSelectedId(key.slice(3));
                      return;
                    }
                    setMode(key);
                  }}
                />
                <Menu
                  className="sider-menu"
                  mode="inline"
                  style={{ borderInlineEnd: 0 }}
                  selectedKeys={mode === "settings" ? ["settings"] : []}
                  items={[{ key: "settings", icon: <SettingOutlined />, label: "Settings" }]}
                  onClick={() => setMode("settings")}
                />
              </div>
            </Sider>
          </ConfigProvider>
          <Content style={{ minWidth: 0, minHeight: 0, overflow: mode === "machines" || mode === "history" ? "hidden" : "auto", background: "#f5f5f5", display: "flex", flexDirection: "column" }}>
            {error ? <Alert style={{ margin: 16 }} type="error" showIcon message={error} /> : null}
            {mode === "history" ? <HistoryPage /> : mode === "machines" ? (
              <Machines
                vm={vm}
                vms={data.vms}
                host={data.host}
                qmp={data.qmp}
                busy={busy}
                summary={pageSummary || `${running.length} running`}
                onStart={start}
                onStop={stop}
                onReset={reset}
                onOpenVm={(id) => { picked.current = true; setSelectedId(id); }}
              />
            ) : (
              <div style={{ padding: 16 }}>
                {mode === "dashboard" ? <DashboardView host={data.host} vms={data.vms} onOpenVm={(id) => { setSelectedId(id); setMode("machines"); }} /> : null}
                {mode === "settings" ? <SettingsView config={data.config} /> : null}
                {mode === "builder" || mode === "creating" || mode === "dump" ? (
                  <Builder
                    mode={mode}
                    config={data.config}
                    catalog={data.catalog}
                    shelf={data.shelf}
                    seed={seed}
                    onOpen={openPage}
                    onMenuRefresh={() => setMenuTick((value) => value + 1)}
                    onSeedConsumed={() => setSeed(null)}
                  />
                ) : null}
                {mode === "resource" || mode === "iso" || mode === "passthrough" ? (
                  <Resource
                    mode={mode}
                    config={data.config}
                    shelf={data.shelf}
                    onOpen={openPage}
                    onTemplate={(draft) => {
                      setSeed(draft);
                      openPage("creating");
                    }}
                  />
                ) : null}
              </div>
            )}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
