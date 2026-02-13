import { app, BrowserWindow } from "electron";
import path from "path";
import { fileURLToPath } from "url";
import fs from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const isDev = !app.isPackaged;
const resolveDistIndexPath = () => {
  const candidates = [
    path.join(app.getAppPath(), "dist", "index.electron.html"),
    path.join(app.getAppPath(), "dist", "index.html"),
    path.join(process.resourcesPath, "app.asar", "dist", "index.electron.html"),
    path.join(process.resourcesPath, "app.asar", "dist", "index.html"),
    path.join(process.resourcesPath, "app", "dist", "index.electron.html"),
    path.join(process.resourcesPath, "app", "dist", "index.html"),
    path.join(__dirname, "dist", "index.electron.html"),
    path.join(__dirname, "dist", "index.html"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[0];
};

async function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "ArX-OS",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  if (isDev) {
    await win.loadURL("http://localhost:5173");
    return;
  }
  await win.loadFile(resolveDistIndexPath());
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});