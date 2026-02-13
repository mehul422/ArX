import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import JSZip from "jszip";
import {
  MissionTargetPayload,
  pollMissionTargetJob,
  submitMissionTarget,
} from "../services/missionTarget";
import { FlightTelemetryGraph } from "./telemetry/FlightTelemetryGraph";
import { PositioningModule } from "../module-r/positioning_index/PositioningModule";
import "./ArxInterface.css";

const ArxInterface: React.FC = () => {
  useEffect(() => {
    const API_BASE =
      (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL || "";
    const resolveDownloadUrl = (path?: string) => {
      if (!path) return "";
      if (path.startsWith("http://") || path.startsWith("https://")) return path;
      const normalized = path.replace(/\\/g, "/");
      if (normalized.startsWith("/downloads/")) return `${API_BASE}/api/v1${normalized}`;
      if (normalized.startsWith("downloads/")) return `${API_BASE}/api/v1/${normalized}`;
      if (normalized.startsWith("backend/tests/")) {
        return `${API_BASE}/api/v1/downloads/${normalized.slice("backend/tests/".length)}`;
      }
      const testsIndex = normalized.indexOf("/backend/tests/");
      if (testsIndex !== -1) {
        return `${API_BASE}/api/v1/downloads/${normalized.slice(
          testsIndex + "/backend/tests/".length
        )}`;
      }
      if (normalized.startsWith("backend/")) {
        const parts = normalized.split("/");
        const filename = parts[parts.length - 1];
        return filename ? `${API_BASE}/api/v1/downloads/${filename}` : "";
      }
      if (normalized.startsWith("/")) return `${API_BASE}${normalized}`;
      return `${API_BASE}/${normalized}`;
    };
    const getFilenameFromUrl = (url: string) => {
      try {
        const parsed = new URL(url, window.location.href);
        const name = parsed.pathname.split("/").pop();
        return name || "download";
      } catch {
        const parts = url.split("/");
        return parts[parts.length - 1] || "download";
      }
    };
    const triggerDownload = async (url: string, filename?: string) => {
      if (!url) return;
      try {
        const response = await fetch(url, { credentials: "include" });
        if (!response.ok) throw new Error(`Download failed: ${response.status}`);
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename || getFilenameFromUrl(url);
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
      } catch (error) {
        console.error(error);
        window.open(url, "_blank");
      }
    };
    const audioCtx = new (window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext)();
    let voiceAudio: HTMLAudioElement | null = null;
    let bgmAudio: HTMLAudioElement | null = null;
    let alarmAudio: HTMLAudioElement | null = null;
    let bootTimeouts: number[] = [];
    let modeXTimeouts: number[] = [];
    let warpInterval: number | null = null;
    let modeXHoverTimer: number | null = null;
    let arxHoverTimer: number | null = null;
    let hasInitializedGrid = false;
    let engineRenderer: any = null;
    let engineComposer: any = null;
    let engineControls: any = null;
    let engineScene: any = null;
    let engineCamera: any = null;
    let engineAnimationId: number | null = null;
    let engineResizeObserver: ResizeObserver | null = null;
    let engineHighlight = 0;
    let engineGlowMaterial: any = null;
    let engineBandMaterial: any = null;
    let telemetryGraph: FlightTelemetryGraph | null = null;
    let hasBooted = false;
    let isTransitioning = false;
    let activeModuleId: string | null = null;
    let isSubPageLocked = false;
    let pendingSubPageType: string | null = null;
    const MODULE_R_FULL_MATERIALS = [
      "Carbon Fiber",
      "Fiberglass",
      "Aramid Fiber",
      "Phenolic",
      "Plywood (Birch)",
      "Plywood",
      "Balsa",
      "Basswood",
      "Spruce",
      "MDF",
      "ABS",
      "PLA",
      "PVC",
      "Polycarbonate",
      "Polystyrene",
      "Polyethylene",
      "Nylon",
      "Delrin",
      "Teflon",
      "Aluminum",
      "Aluminum 6061-T6",
      "Titanium",
      "Steel (Stainless)",
      "Steel (Mild)",
      "Steel",
      "Brass",
      "Copper",
      "Cardboard",
      "Kraft Paper",
      "Hard Paper",
      "Plastic",
    ] as const;
    const MODULE_R_FULL_MATERIAL_OPTIONS_HTML = MODULE_R_FULL_MATERIALS.map(
      (material) => `<option value="${material}">${material}</option>`
    ).join("");
    const MODULE_R_PARACHUTE_LIBRARY_URL =
      "https://github.com/dbcook/openrocket-database/tree/master/orc";
    const MODULE_R_PARACHUTE_LIBRARY = [
      { id: "orc-12in", name: "Parachute 12 in", mass_lb: 0.02, drag_coefficient: 0.8, material: "Nylon" },
      { id: "orc-18in", name: "Parachute 18 in", mass_lb: 0.04, drag_coefficient: 0.82, material: "Nylon" },
      { id: "orc-24in", name: "Parachute 24 in", mass_lb: 0.07, drag_coefficient: 0.84, material: "Nylon" },
      { id: "orc-36in", name: "Parachute 36 in", mass_lb: 0.12, drag_coefficient: 0.86, material: "Nylon" },
      { id: "orc-48in", name: "Parachute 48 in", mass_lb: 0.2, drag_coefficient: 0.88, material: "Nylon" },
    ] as const;

    const floatSound = new Audio(
      "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/axr%20float.mp3"
    );
    const modeXHoverSound = new Audio(
      "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/mode%20x%20option%20slexes.mp3"
    );
    const popupSound = new Audio(
      "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/pop%20up.mp3"
    );
    const warpAudio = new Audio(
      "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/try%20one.mp3"
    );
    const landingAudio = new Audio(
      "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/ethmusic.mp3"
    );
    const landingVolumeDefault = 0.5;
    landingAudio.loop = true;
    landingAudio.volume = landingVolumeDefault;

    let hasLaunched = false;
    let landingAudioStarted = false;
    let enableAudio: () => void = () => {};
    let loggedInEmail: string | null = null;

    const showPressAnyKey = () => {
      let layer = document.getElementById("press-any-key-layer");
      if (!layer) {
        layer = document.createElement("div");
        layer.id = "press-any-key-layer";
        const text = document.createElement("div");
        text.id = "press-any-key-text";
        text.innerText = "PRESS ANY KEY";
        layer.appendChild(text);
        document.body.appendChild(layer);
      }
      layer.classList.add("visible");
      (layer as HTMLElement).style.display = "flex";
      (layer as HTMLElement).style.opacity = "1";
    };
    const hidePressAnyKey = () => {
      const layer = document.getElementById("press-any-key-layer");
      if (!layer) return;
      layer.classList.remove("visible");
      (layer as HTMLElement).style.opacity = "0";
      (layer as HTMLElement).style.display = "none";
    };
    const updateAuthUI = () => {
      const navLoginBtn = document.querySelector(
        '.nav-right [data-action="INIT"]'
      ) as HTMLButtonElement | null;
      const dropdownLoginItem = document.querySelector(
        '.dropdown-menu [data-action="INIT"]'
      ) as HTMLElement | null;
      if (loggedInEmail) {
        const label = loggedInEmail.slice(0, 5).toUpperCase();
        if (navLoginBtn) navLoginBtn.textContent = label;
        if (dropdownLoginItem) dropdownLoginItem.textContent = "LOG OUT";
      } else {
        if (navLoginBtn) navLoginBtn.textContent = "Initialize";
        if (dropdownLoginItem) dropdownLoginItem.textContent = "LOG IN";
      }
    };

    const getLaunchInputs = (container: Element) => {
      const get = (name: string) =>
        (container.querySelector(`input[name="${name}"]`) as HTMLInputElement | null) || null;
      return {
        altitude: get("launch_altitude_ft"),
        temperature: get("temperature_f"),
        wind: get("wind_speed_mph"),
        rodLength: get("rod_length_ft"),
        angle: get("launch_angle_deg"),
      };
    };

    const loadLaunchProfile = () => {
      try {
        const stored = window.localStorage.getItem("arx_launch_profile");
        if (!stored) return null;
        return JSON.parse(stored) as Record<string, number>;
      } catch (error) {
        console.warn("Invalid arx_launch_profile JSON", error);
        return null;
      }
    };

    const saveLaunchProfile = (profile: Record<string, number>) => {
      window.localStorage.setItem("arx_launch_profile", JSON.stringify(profile));
    };

    const openLaunchModal = () => {
      const modal = document.getElementById("launchModal");
      if (!modal) return;
      const inputs = getLaunchInputs(modal);
      const stored = loadLaunchProfile();
      if (stored) {
        if (inputs.altitude && Number.isFinite(stored.launch_altitude_ft)) {
          inputs.altitude.value = String(stored.launch_altitude_ft);
        }
        if (inputs.temperature && Number.isFinite(stored.temperature_f)) {
          inputs.temperature.value = String(stored.temperature_f);
        }
        if (inputs.wind && Number.isFinite(stored.wind_speed_mph)) {
          inputs.wind.value = String(stored.wind_speed_mph);
        }
        if (inputs.rodLength && Number.isFinite(stored.rod_length_ft)) {
          inputs.rodLength.value = String(stored.rod_length_ft);
        }
        if (inputs.angle && Number.isFinite(stored.launch_angle_deg)) {
          inputs.angle.value = String(stored.launch_angle_deg);
        }
      }
      modal.classList.add("visible");
      modal.setAttribute("aria-hidden", "false");
    };

    const closeLaunchModal = () => {
      const modal = document.getElementById("launchModal");
      if (!modal) return;
      modal.classList.remove("visible");
      modal.setAttribute("aria-hidden", "true");
    };

    const startLandingAudio = () => {
      if (landingAudioStarted || hasLaunched) return;
      landingAudioStarted = true;
      landingAudio.play().catch(() => {});
    };

    const playPromise = landingAudio.play();
    if (playPromise !== undefined) {
      playPromise.catch(() => {
        enableAudio = () => {
          if (hasLaunched || landingAudioStarted) {
            window.removeEventListener("click", enableAudio);
            window.removeEventListener("keydown", enableAudio);
            window.removeEventListener("touchstart", enableAudio);
            return;
          }
          startLandingAudio();
          window.removeEventListener("click", enableAudio);
          window.removeEventListener("keydown", enableAudio);
          window.removeEventListener("touchstart", enableAudio);
        };
        window.addEventListener("click", enableAudio);
        window.addEventListener("keydown", enableAudio);
        window.addEventListener("touchstart", enableAudio);
      });
    }

    window.addEventListener("pointerdown", startLandingAudio, { once: true });

    // STAR LOGIC
    const canvas = document.getElementById("stars") as HTMLCanvasElement | null;
    const ctx = canvas?.getContext("2d") || null;
    let stars: Array<{ x: number; y: number; z: number; color: string }> = [];
    const STAR_COUNT = 2500;
    let speed = 0.5;
    let warp = false;
    let animationId: number | null = null;

    const resize = () => {
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener("resize", resize);
    resize();

    const initStars = () => {
      if (!canvas) return;
      stars = [];
      for (let i = 0; i < STAR_COUNT; i++) {
        stars.push({
          x: (Math.random() - 0.5) * canvas.width,
          y: (Math.random() - 0.5) * canvas.height,
          z: Math.random() * canvas.width,
          color: Math.random() > 0.3 ? "200, 240, 255" : "255, 255, 255",
        });
      }
    };

    const animateStars = () => {
      if (!canvas || !ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = "lighter";
      let cx = canvas.width / 2;
      let cy = canvas.height / 2;
      if (warp && speed > 20) {
        cx += (Math.random() - 0.5) * (speed / 4);
        cy += (Math.random() - 0.5) * (speed / 4);
      }
      for (const s of stars) {
        s.z -= speed;
        if (s.z <= 0) {
          s.z = canvas.width;
          s.x = (Math.random() - 0.5) * canvas.width;
          s.y = (Math.random() - 0.5) * canvas.height;
        }
        const k = 400 / s.z;
        const x = s.x * k + cx;
        const y = s.y * k + cy;
        const trailLength = warp ? speed * 1.5 : speed * 5;
        const prevZ = s.z + trailLength;
        const prevK = 400 / prevZ;
        const px = s.x * prevK + cx;
        const py = s.y * prevK + cy;
        const depthAlpha = 1 - s.z / canvas.width;
        if (x >= 0 && x <= canvas.width && y >= 0 && y <= canvas.height) {
          ctx.beginPath();
          ctx.strokeStyle = `rgba(${s.color}, ${depthAlpha})`;
          let thickness = (1 - s.z / canvas.width) * 3;
          if (warp) thickness *= 1.5;
          ctx.lineWidth = Math.max(0.1, thickness);
          ctx.lineCap = "round";
          ctx.moveTo(px, py);
          ctx.lineTo(x, y);
          ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      animationId = requestAnimationFrame(animateStars);
    };
    initStars();
    animateStars();

    const startWarp = () => {
      warp = true;
      document.body.classList.add("hyperspace-active");
      skipBtn?.classList.add("visible");
      warpInterval = window.setInterval(() => {
        if (speed < 80) speed *= 1.05;
        if (speed < 2) speed += 0.5;
        if (speed > 80 && warpInterval) clearInterval(warpInterval);
      }, 20);
    };
    const stopWarp = () => {
      warp = false;
      speed = 0.5;
      if (warpInterval) clearInterval(warpInterval);
    };

    const waitForAudioEnd = (audio: HTMLAudioElement | null) =>
      new Promise<void>((resolve) => {
        if (!audio) return resolve();
        const handler = () => resolve();
        audio.addEventListener("ended", handler, { once: true });
      });

    const playBootSound = () => {
      if (hasBooted) return;
      if (audioCtx.state === "suspended") audioCtx.resume();
      bgmAudio = new Audio(
        "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/sound%20track%20ai'%20main.mp3"
      );
      bgmAudio.volume = 1.0;
      voiceAudio = new Audio(
        "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/main%20jarvis.mp3"
      );
      voiceAudio.volume = Math.min(1, 1.4);
      voiceAudio.play().catch(() => {});
      bgmAudio.play().catch(() => {});
      hasBooted = true;
    };

    const duckLandingAudio = () => {
      landingAudio.muted = false;
      if (hasLaunched) {
        landingAudio.pause();
      }
      landingAudio.currentTime = 0;
      landingAudio.volume = 0.0;
    };

    const restoreLandingAudio = () => {
      landingAudio.muted = false;
      landingAudio.volume = 0.05;
      landingAudio.play().catch(() => {});
    };

    const randomizeDashboardData = () => {
      const press = Math.floor(Math.random() * (310 - 290) + 290);
      const lox = Math.floor(Math.random() * (99 - 88) + 88);
      const ch4 = Math.floor(Math.random() * (99 - 88) + 88);

      const elPress = document.getElementById("val-pressure");
      const elLox = document.getElementById("val-lox");
      const elCh4 = document.getElementById("val-ch4");

      if (elPress) elPress.innerText = String(press);
      if (elLox) elLox.innerText = `${lox}%`;
      if (elCh4) elCh4.innerText = `${ch4}%`;

      const sys = (Math.random() * 90).toFixed(3);
      const arm = (Math.random() * (100 - 90) + 90).toFixed(1);
      const net = Math.floor(Math.random() * (200 - 100) + 100);

      const elSys = document.getElementById("val-sys");
      const elArm = document.getElementById("val-arm");
      const elNet = document.getElementById("val-net");

      if (elSys) elSys.innerText = sys;
      if (elArm) elArm.innerText = `${arm}%`;
      if (elNet) elNet.innerText = `${net} TB/s`;

      const lat = (34.05 + (Math.random() - 0.5) * 0.2).toFixed(2);
      const lon = (-118.25 + (Math.random() - 0.5) * 0.2).toFixed(2);
      const elModex = document.getElementById("val-modex");
      if (elModex) elModex.innerText = `LAT: ${lat} LON: ${lon}`;
    };

    const attachHoverSounds = () => {
      const standardCards = document.querySelectorAll(
        ".module-card:not(.red-alert)"
      );
      const modeXCard = document.getElementById("modeXBtn");
      standardCards.forEach((card) => {
        const enter = () => {
          arxHoverTimer = window.setTimeout(() => {
            const sound = floatSound.cloneNode() as HTMLAudioElement;
            sound.volume = 0.5;
            sound.play().catch(() => {});
          }, 200);
        };
        const leave = () => {
          if (arxHoverTimer) clearTimeout(arxHoverTimer);
        };
        card.addEventListener("mouseenter", enter);
        card.addEventListener("mouseleave", leave);
      });
      if (modeXCard) {
        const enter = () => {
          modeXHoverTimer = window.setTimeout(() => {
            const sound = modeXHoverSound.cloneNode() as HTMLAudioElement;
            sound.volume = 0.6;
            sound.play().catch(() => {});
          }, 200);
        };
        const leave = () => {
          if (modeXHoverTimer) clearTimeout(modeXHoverTimer);
        };
        modeXCard.addEventListener("mouseenter", enter);
        modeXCard.addEventListener("mouseleave", leave);
      }
      const modalBtns = document.querySelectorAll("#modeXModal button");
      modalBtns.forEach((btn) => {
        btn.addEventListener("mouseenter", () => {
          const sound = floatSound.cloneNode() as HTMLAudioElement;
          sound.volume = 0.5;
          sound.play().catch(() => {});
        });
      });
    };

    const skipIntro = () => {
      if (hasLaunched) {
        landingAudio.pause();
      }
      landingAudio.currentTime = 0;
      warpAudio.pause();
      warpAudio.currentTime = 0;

      bootTimeouts.forEach((id) => clearTimeout(id));
      bootTimeouts = [];
      stopWarp();
      if (landingContainer) landingContainer.style.display = "none";
      if (flash) flash.style.display = "none";
      if (bootText) bootText.style.display = "none";
      if (skipBtn) skipBtn.style.display = "none";
      document.body.style.backgroundColor = "black";
      document.body.classList.add("dashboard-mode");
      if (dashboardContainer) dashboardContainer.style.display = "block";

      randomizeDashboardData();

      const rings = document.querySelectorAll(".reactor-ring, .reactor-ring-inner");
      const nav = document.getElementById("topNav");
      const panels = document.querySelectorAll(".side-panel");
      const cards = document.querySelectorAll(".module-card");
      rings.forEach((r) => ((r as HTMLElement).style.opacity = "0.8"));
      nav?.classList.remove("boot-hidden");
      nav?.classList.add("boot-visible");
      panels.forEach((p) => {
        p.classList.remove("boot-hidden");
        p.classList.add("boot-visible");
      });
      cards.forEach((card) => {
        card.classList.remove("boot-scale-hidden");
        card.classList.add("boot-scale-visible");
      });
      if (audioCtx.state === "suspended") audioCtx.resume();
      if (voiceAudio) {
        voiceAudio.pause();
        voiceAudio.currentTime = 0;
      }
      if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
      }
      landingAudio.currentTime = 0;
      landingAudio.play().catch(() => {});
      hasBooted = true;
      attachHoverSounds();

      requestAnimationFrame(() => {
        updateRocketSize();
      });
    };

    const btn = document.getElementById("start-btn") as HTMLButtonElement | null;
    const hero = document.getElementById("hero-section");
    const flash = document.getElementById("warp-flash");
    const landingContainer = document.getElementById("landing-container");
    const dashboardContainer = document.getElementById("dashboard-container");
    const bootText = document.getElementById("boot-text");
    const skipBtn = document.getElementById("skip-btn");

    const startClick = (e: Event) => {
      e.preventDefault();
      hasLaunched = true;
      duckLandingAudio();
      let resolveWarpDone: (() => void) | null = null;
      const warpDone = new Promise<void>((resolve) => {
        resolveWarpDone = resolve;
      });

      warpAudio.currentTime = 0;
      warpAudio.volume = 1.0;
      warpAudio.play().catch(() => {});
      if (audioCtx.state === "suspended") audioCtx.resume();
      startWarp();
      hero?.classList.add("launching");
      bootTimeouts.push(
        window.setTimeout(() => {
          warpAudio.pause();
          warpAudio.currentTime = 0;
          resolveWarpDone?.();
          flash?.classList.add("active");
          bootTimeouts.push(
            window.setTimeout(() => {
              stopWarp();
              if (landingContainer) landingContainer.style.display = "none";
              if (skipBtn) skipBtn.style.display = "none";
              document.body.style.backgroundColor = "black";
              bootText?.classList.add("boot-text-visible");
              playBootSound();
              Promise.all([
                warpDone,
                waitForAudioEnd(voiceAudio),
                waitForAudioEnd(bgmAudio),
              ]).then(
                () => {
                  restoreLandingAudio();
                }
              );
              bootTimeouts.push(
                window.setTimeout(() => {
                  bootText?.classList.remove("boot-text-visible");
                  document.body.classList.add("dashboard-mode");
                  if (!hasInitializedGrid) {
                    hasInitializedGrid = true;
                    document.body.classList.add("grid-init-collapse");
                    window.setTimeout(() => {
                      document.body.classList.add("grid-init-directional");
                    }, 300);
                    window.setTimeout(() => {
                      document.body.classList.add("grid-init-holograms");
                    }, 650);
                    window.setTimeout(() => {
                      document.body.classList.add("grid-init-final");
                    }, 900);
                  }
                  if (dashboardContainer) dashboardContainer.style.display = "block";
                  if (flash) {
                    flash.style.transition = "opacity 1s ease";
                    flash.style.opacity = "0";
                    bootTimeouts.push(
                      window.setTimeout(() => {
                        flash.style.display = "none";
                      }, 1000)
                    );
                  }
                  const rings = document.querySelectorAll(
                    ".reactor-ring, .reactor-ring-inner"
                  );
                  const nav = document.getElementById("topNav");
                  const panels = document.querySelectorAll(".side-panel");
                  const cards = document.querySelectorAll(".module-card");
                  rings.forEach((r) => ((r as HTMLElement).style.opacity = "0.8"));
                  bootTimeouts.push(
                    window.setTimeout(() => {
                      nav?.classList.remove("boot-hidden");
                      nav?.classList.add("boot-visible");
                    }, 500)
                  );
                  bootTimeouts.push(
                    window.setTimeout(() => {
                      panels.forEach((p) => {
                        p.classList.remove("boot-hidden");
                        p.classList.add("boot-visible");
                      });
                      randomizeDashboardData();
                      updateRocketSize();
                    }, 1000)
                  );
                  cards.forEach((card, index) => {
                    bootTimeouts.push(
                      window.setTimeout(() => {
                        card.classList.remove("boot-scale-hidden");
                        card.classList.add("boot-scale-visible");
                      }, 1500 + index * 200)
                    );
                  });
                  bootTimeouts.push(
                    window.setTimeout(() => {
                      attachHoverSounds();
                    }, 2000)
                  );
                }, 2000)
              );
            }, 1000)
          );
        }, 2500)
      );
    };

    btn?.addEventListener("click", startClick);
    skipBtn?.addEventListener("click", skipIntro);

    // NAVIGATION LOGIC
    const selectModule = (id: string, element: HTMLElement) => {
      if (isTransitioning) return;
      activeModuleId = id;
      if (id === "ADVANCED") {
        const sound = popupSound.cloneNode() as HTMLAudioElement;
        sound.volume = 0.7;
        sound.play().catch(() => {});
        const modeXModal = document.getElementById("modeXModal");
        if (modeXModal) modeXModal.style.display = "flex";
        return;
      }
      isTransitioning = true;

      const mapping: Record<
        string,
        {
          text: string;
          title: string;
          ringClass: string;
          ringInnerClass: string;
          color: string;
          gridColor: string;
          reactorColor: string;
        }
      > = {
        SYSTEM: {
          text: "A",
          title: "MOTOR DEVELOPMENT",
          ringClass: "ring-green",
          ringInnerClass: "ring-green-inner",
          color: "#00ff00",
          gridColor: "0, 255, 0",
          reactorColor: "#00ff00",
        },
        ARMOR: {
          text: "R",
          title: "ROCKET DEVELOPMENT",
          ringClass: "ring-yellow",
          ringInnerClass: "ring-yellow-inner",
          color: "#ffff00",
          gridColor: "255, 255, 0",
          reactorColor: "#ffff00",
        },
        NETWORK: {
          text: "X",
          title: "SIMULATIONS",
          ringClass: "ring-white",
          ringInnerClass: "ring-white-inner",
          color: "#ffffff",
          gridColor: "255, 255, 255",
          reactorColor: "#ffffff",
        },
      };
      const config = mapping[id];
      if (!config) {
        isTransitioning = false;
        return;
      }

      document.documentElement.style.setProperty("--grid-color", config.gridColor);
      document.documentElement.style.setProperty("--reactor-color", config.reactorColor);

      if (voiceAudio) {
        voiceAudio.pause();
        voiceAudio.currentTime = 0;
      }
      if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
      }
      const sound = popupSound.cloneNode() as HTMLAudioElement;
      sound.volume = 0.5;
      sound.play().catch(() => {});
      const letterSpan = element.querySelector(".card-label") as HTMLElement | null;
      if (!letterSpan) return;
      const rect = letterSpan.getBoundingClientRect();
      const floater = document.createElement("span");
      floater.innerText = config.text;
      floater.dataset.title = config.title;
      floater.className = "floating-letter";
      floater.style.top = `${rect.top}px`;
      floater.style.left = `${rect.left}px`;
      floater.style.width = `${rect.width}px`;
      floater.style.height = `${rect.height}px`;
      floater.style.color = config.color;
      floater.style.fontSize = getComputedStyle(letterSpan).fontSize;
      floater.id = "activeFloater";
      floater.style.cursor = "default";
      floater.style.pointerEvents = "none";
      document.body.appendChild(floater);
      requestAnimationFrame(() => {
        floater.classList.add("centered-massive");
        document.getElementById("topNav")?.classList.add("fade-exit");
        document.querySelectorAll(".side-panel").forEach((el) => el.classList.add("fade-exit"));
        document.getElementById("moduleGrid")?.classList.add("fade-exit");
        document.getElementById("ring1")?.classList.add(config.ringClass);
        document.getElementById("ring2")?.classList.add(config.ringInnerClass);
        showPressAnyKey();
      });
      const subPageBtn = document.getElementById("subPageBtn") as HTMLButtonElement | null;
      if (subPageBtn) {
        subPageBtn.innerText = "RETURN TO DASHBOARD";
        subPageBtn.onclick = resetDashboard;
      }
      setTimeout(() => {
        document.getElementById("subPage")?.classList.add("active");
      }, 800);
    };

    const getMissionTargetPayload = (): MissionTargetPayload | null => {
      const globalPayload = (window as unknown as { ARX_MISSION_TARGET_PAYLOAD?: MissionTargetPayload })
        .ARX_MISSION_TARGET_PAYLOAD;
      if (globalPayload) return globalPayload;
      const stored = window.localStorage.getItem("arx_mission_target_payload");
      if (!stored) return null;
      try {
        return JSON.parse(stored) as MissionTargetPayload;
      } catch (error) {
        console.warn("Invalid arx_mission_target_payload JSON", error);
        return null;
      }
    };

    const MISSION_TIMEOUT_MS = 60 * 60 * 1000;

    const runMissionTarget = async () => {
      const payload = getMissionTargetPayload();
      if (!payload) {
        console.warn("Mission target payload missing; set window.ARX_MISSION_TARGET_PAYLOAD");
        window.dispatchEvent(
          new CustomEvent("arx:mission-target:error", {
            detail: { message: "Mission target payload missing" },
          })
        );
        return;
      }
      window.dispatchEvent(new CustomEvent("arx:mission-target:status", { detail: { status: "start" } }));
      try {
        const job = await submitMissionTarget(payload);
        window.localStorage.setItem("arx_mission_target_job_id", job.id);
        window.dispatchEvent(
          new CustomEvent("arx:mission-target:status", { detail: { status: "submitted", jobId: job.id } })
        );
        const latestJobId = window.localStorage.getItem("arx_mission_target_job_id") || job.id;
        const finished = await pollMissionTargetJob(latestJobId, {
          timeoutMs: MISSION_TIMEOUT_MS,
          intervalMs: 15000,
        });
        window.dispatchEvent(
          new CustomEvent("arx:mission-target:status", { detail: { status: finished.status, job: finished } })
        );
      } catch (error) {
        console.error("Mission target flow failed", error);
        window.dispatchEvent(
          new CustomEvent("arx:mission-target:error", {
            detail: { message: "Mission target flow failed", error },
          })
        );
      }
    };

    const initiateArcSequence = (floater: HTMLElement) => {
      document.getElementById("backBtnContainer")?.classList.add("hidden-fast");
      document.getElementById("spacebar-hint")?.classList.remove("visible");
      hidePressAnyKey();
      document.getElementById("arc-reactor-overlay")?.classList.remove("arc-reactor-corner");
      document.getElementById("ring1")?.classList.remove("hidden-fast");
      document.getElementById("ring2")?.classList.remove("hidden-fast");
      floater.classList.add("force-vanish");
      const titleEl = document.getElementById("activeModuleTitle");
      if (titleEl) titleEl.classList.add("float-up-exit");
      document.getElementById("arc-reactor-overlay")?.classList.add("active");
      document.querySelector(".close-x-btn")?.classList.add("active");
      if (activeModuleId) {
        setTimeout(() => {
          const overlay = document.getElementById("arc-reactor-overlay");
          const onFloatEnd = () => {
            overlay?.removeEventListener("transitionend", onFloatEnd);
            document.getElementById("ring1")?.classList.add("hidden-fast");
            document.getElementById("ring2")?.classList.add("hidden-fast");
          };
          overlay?.addEventListener("transitionend", onFloatEnd, { once: true });
          overlay?.classList.add("arc-reactor-corner");
          document.body.classList.add("grid-mat-active");
          document.getElementById("activeFloater")?.remove();
          if (activeModuleId === "SYSTEM" || activeModuleId === "ARMOR" || activeModuleId === "NETWORK") {
            document.body.classList.add("grid-only");
            document.body.classList.remove("panel-active");
            awaitSubPageKey(activeModuleId);
          }
        }, 4000);
      }
    };

    const closeArcSequence = () => {
      document.getElementById("arc-reactor-overlay")?.classList.remove("active");
      document.getElementById("arc-reactor-overlay")?.classList.remove("arc-reactor-corner");
      document.body.classList.remove("grid-mat-active");
      document.body.classList.remove("holo-active");
      document.querySelector(".close-x-btn")?.classList.remove("active");
      document.getElementById("spacebar-hint")?.classList.remove("visible");
      hidePressAnyKey();
      setTimeout(() => resetDashboard(), 500);
    };

    const handleNavClick = (type: string) => {
      if (isTransitioning) return;
      isTransitioning = true;
      pendingSubPageType = null;
      isSubPageLocked = false;
      if (type === "INIT" && loggedInEmail) {
        loggedInEmail = null;
        updateAuthUI();
        resetDashboard();
        isTransitioning = false;
        return;
      }
      const sound = popupSound.cloneNode() as HTMLAudioElement;
      sound.volume = 0.5;
      sound.play().catch(() => {});
      if (voiceAudio) {
        voiceAudio.pause();
        voiceAudio.currentTime = 0;
      }
      if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
      }
      const subPageContent = document.getElementById("subPageContent");
      if (subPageContent) subPageContent.innerHTML = "";

      let ringClass: string | undefined;
      let ringInnerClass: string | undefined;
      let color = "#00f3ff";
      let textContent = "";
      let isPricing = false;
      let newGridColor = "0, 243, 255";

      if (type === "INIT") {
        textContent = "LOG IN";
      } else if (type === "NEW") {
        ringClass = "ring-teal";
        ringInnerClass = "ring-teal-inner";
        color = "#00ffaa";
        textContent = "NEW USER";
        newGridColor = "0, 255, 170";
      } else if (type === "PROTO") {
        ringClass = "ring-gold";
        ringInnerClass = "ring-gold-inner";
        color = "#ffd700";
        textContent = "CONTACT US";
        newGridColor = "255, 215, 0";
      } else if (type === "PRICING") {
        ringClass = "ring-purple";
        ringInnerClass = "ring-purple-inner";
        color = "#b026ff";
        textContent = "PRICING";
        isPricing = true;
        newGridColor = "176, 38, 255";
      }

      document.documentElement.style.setProperty("--grid-color", newGridColor);
      document.documentElement.style.setProperty("--page-accent", color);

      document.getElementById("topNav")?.classList.add("fade-exit");
      document.querySelectorAll(".side-panel").forEach((el) => el.classList.add("fade-exit"));
      document.getElementById("moduleGrid")?.classList.add("fade-exit");
      const r1 = document.getElementById("ring1");
      const r2 = document.getElementById("ring2");
      if (ringClass && r1) r1.classList.add(ringClass);
      if (ringInnerClass && r2) r2.classList.add(ringInnerClass);

      const floater = document.createElement("span");
      floater.innerText = textContent;
      floater.className = "floating-letter centered-contained-word";
      floater.style.color = color;
      floater.style.fontSize = "3rem";
      floater.style.position = "fixed";
      floater.style.top = isPricing ? "15%" : "50%";
      floater.style.left = "50%";
      floater.style.transform = "translate(-50%, -50%)";
      floater.style.opacity = "0";
      floater.style.transition = "opacity 1s ease, top 1s ease";
      floater.id = "activeFloater";
      document.body.appendChild(floater);
      const loginLayer = document.getElementById("login-layer");
      if (loginLayer) loginLayer.innerHTML = "";
      if (subPageContent) {
        if (isPricing) {
          subPageContent.innerHTML = `
            <div class="pricing-notice-modal" data-open="true" role="dialog" aria-modal="true">
              <div class="pricing-notice-panel">
                <div class="panel-header">PRICING NOTICE</div>
                <div class="modal-text">everything is on us right now, pricing initializes in V2.0)</div>
                <div class="arx-form-actions">
                  <button type="button" class="arx-btn" data-action="close-pricing-notice">OK</button>
                </div>
              </div>
            </div>
            <div class="pricing-grid">
              <article class="pricing-box">
                <div class="pricing-tier-name">LAUNCH</div>
                <div class="pricing-price-row">
                  <span class="pricing-current-price">$0</span>
                  <span class="pricing-period">/ month</span>
                </div>
                <ul class="pricing-feature-list">
                  <li>Access to AR</li>
                  <li>
                    Access to X (Limited)
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                  <li>
                    Access to Module X (Limited)
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                </ul>
              </article>
              <article class="pricing-box">
                <div class="pricing-tier-name">ORBIT</div>
                <div class="pricing-price-row">
                  <span class="pricing-old-price">$10</span>
                  <span class="pricing-current-price">$5</span>
                  <span class="pricing-period">/ month</span>
                </div>
                <div class="pricing-discount-note">Early Adopter Discount</div>
                <ul class="pricing-feature-list">
                  <li>Unlimited access to AR</li>
                  <li>
                    Unlimited access to X
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                  <li>
                    Access to Module X (Limited)
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                </ul>
              </article>
              <article class="pricing-box">
                <div class="pricing-tier-name">ESCAPE</div>
                <div class="pricing-price-row">
                  <span class="pricing-old-price">$30</span>
                  <span class="pricing-current-price">$15</span>
                  <span class="pricing-period">/ month</span>
                </div>
                <div class="pricing-discount-note">Early Adopter Discount</div>
                <ul class="pricing-feature-list">
                  <li>Infinite access to AR</li>
                  <li>
                    Infinite access to X
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                  <li>
                    Infinite access to Module X
                    <span class="pricing-soon-tag">[COMING SOON]</span>
                  </li>
                </ul>
              </article>
            </div>
          `;
          const pricingNotice = subPageContent.querySelector(".pricing-notice-modal") as
            | HTMLElement
            | null;
          pricingNotice?.addEventListener("click", (event) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;
            if (
              target === pricingNotice ||
              target.closest('[data-action="close-pricing-notice"]')
            ) {
              pricingNotice.setAttribute("data-open", "false");
            }
          });
          setTimeout(() => {
            document.querySelectorAll(".pricing-box").forEach((box) => {
              box.addEventListener("mouseenter", () => {
                const s = floatSound.cloneNode() as HTMLAudioElement;
                s.volume = 0.5;
                s.play().catch(() => {});
              });
            });
          }, 100);
        }
      }
      requestAnimationFrame(() => {
        floater.style.opacity = "1";
      });
      const subPageBtn = document.getElementById("subPageBtn") as HTMLButtonElement | null;
      if (subPageBtn) {
        subPageBtn.innerText = "RETURN TO DASHBOARD";
        subPageBtn.onclick = resetDashboard;
      }
      setTimeout(() => {
        document.getElementById("subPage")?.classList.add("active");
        if (type === "PRICING") {
          floater.style.opacity = "0";
          window.setTimeout(() => {
            if (floater.parentElement) floater.remove();
          }, 420);
        }
        if (type === "INIT" || type === "NEW" || type === "PROTO") {
          document.getElementById("subPage")?.classList.add("form-active");
          document
            .getElementById("arc-reactor-overlay")
            ?.classList.add("active", "form-mode");
        }
        if (type === "INIT") {
          if (loginLayer) {
            loginLayer.innerHTML = `
              <form class="subpage-form login-layer-form" data-form="login" novalidate>
                <div class="form-title">LOGIN ACCESS</div>
                <div class="form-subtitle">SECURE AUTHENTICATION REQUIRED</div>
                <div class="arx-field">
                  <input type="email" name="email" placeholder=" " autocomplete="email" required />
                  <label>YOUR EMAIL</label>
                </div>
                <div class="arx-field">
                  <input type="password" name="password" placeholder=" " autocomplete="current-password" required />
                  <label>ACCESS CODE</label>
                </div>
                <div class="form-status"></div>
                <div class="arx-form-actions">
                  <button type="submit" class="arx-btn">Authorize</button>
                  <button type="button" class="arx-btn" id="login-clear">Clear</button>
                </div>
              </form>
            `;
            bindFormActions(loginLayer);
          }
        } else if (type === "NEW") {
          if (loginLayer) {
            loginLayer.innerHTML = `
              <form class="subpage-form login-layer-form" data-form="new" novalidate>
                <div class="form-title">NEW USER</div>
                <div class="form-subtitle">REGISTER ARX ACCESS</div>
                <div class="arx-field">
                  <input type="text" name="name" placeholder=" " autocomplete="name" required />
                  <label>YOUR NAME</label>
                </div>
                <div class="arx-field">
                  <input type="email" name="email" placeholder=" " autocomplete="email" required />
                  <label>YOUR EMAIL</label>
                </div>
                <div class="arx-field">
                  <input
                    type="password"
                    name="password"
                    placeholder=" "
                    autocomplete="new-password"
                    required
                  />
                  <label>YOUR PASSWORD</label>
                </div>
                <div class="arx-field dob-field">
                  <div class="dob-inputs">
                    <input
                      type="text"
                      name="dob_month"
                      inputmode="numeric"
                      pattern="[0-9]*"
                      maxlength="2"
                      placeholder="MM"
                      autocomplete="bday-month"
                      required
                    />
                    <span class="dob-sep">/</span>
                    <input
                      type="text"
                      name="dob_day"
                      inputmode="numeric"
                      pattern="[0-9]*"
                      maxlength="2"
                      placeholder="DD"
                      autocomplete="bday-day"
                      required
                    />
                    <span class="dob-sep">/</span>
                    <input
                      type="text"
                      name="dob_year"
                      inputmode="numeric"
                      pattern="[0-9]*"
                      maxlength="4"
                      placeholder="YYYY"
                      autocomplete="bday-year"
                      required
                    />
                    <button
                      type="button"
                      class="dob-calendar-btn"
                      aria-label="Open calendar"
                    ></button>
                  </div>
                  <label>DATE OF BIRTH</label>
                  <div class="dob-age" aria-live="polite"></div>
                </div>
                <div class="form-status"></div>
                <div class="arx-form-actions">
                  <button type="submit" class="arx-btn">Register</button>
                  <button type="button" class="arx-btn" id="newuser-clear">Reset</button>
                </div>
              </form>
            `;
            bindFormActions(loginLayer);
          }
        } else if (type === "PROTO") {
          if (loginLayer) {
            loginLayer.innerHTML = `
              <form class="subpage-form login-layer-form" data-form="proto" novalidate>
                <div class="form-title">PROTOCOL 8</div>
                <div class="form-subtitle">SECURE CONTACT CHANNEL</div>
                <div class="arx-field">
                  <input type="text" name="name" placeholder=" " autocomplete="name" required />
                  <label>YOUR NAME</label>
                </div>
                <div class="arx-field">
                  <input type="email" name="email" placeholder=" " autocomplete="email" required />
                  <label>YOUR EMAIL</label>
                </div>
                <div class="arx-field">
                  <textarea name="message" placeholder=" " required></textarea>
                  <label>MISSION BRIEF</label>
                </div>
                <div class="form-status"></div>
                <div class="arx-form-actions">
                  <button type="submit" class="arx-btn">Transmit</button>
                  <button type="button" class="arx-btn" id="proto-clear">Clear</button>
                </div>
              </form>
            `;
            bindFormActions(loginLayer);
          }
        }
      }, 500);
    };

    const parseDobParts = (monthRaw: string, dayRaw: string, yearRaw: string) => {
      const month = Number(monthRaw);
      const day = Number(dayRaw);
      const year = Number(yearRaw);
      if (!Number.isInteger(month) || !Number.isInteger(day) || !Number.isInteger(year)) {
        return { valid: false as const, date: null as Date | null };
      }
      // Must be a real positive year and non-future date.
      if (year <= 0 || month < 1 || month > 12 || day < 1 || day > 31) {
        return { valid: false as const, date: null as Date | null };
      }
      const date = new Date(year, month - 1, day);
      const isExact =
        date.getFullYear() === year &&
        date.getMonth() === month - 1 &&
        date.getDate() === day;
      if (!isExact) {
        return { valid: false as const, date: null as Date | null };
      }
      const now = new Date();
      if (date.getTime() > now.getTime()) {
        return { valid: false as const, date: null as Date | null };
      }
      return { valid: true as const, date };
    };

    const setupDobFields = (scope: Element | null) => {
      if (!scope) return;
      const dobFields = scope.querySelectorAll(".dob-field");
      dobFields.forEach((field) => {
        const fieldEl = field as HTMLElement;
        if (fieldEl.getAttribute("data-dob-bound") === "true") return;
        fieldEl.setAttribute("data-dob-bound", "true");
        const monthInput = fieldEl.querySelector(
          'input[name="dob_month"]'
        ) as HTMLInputElement | null;
        const dayInput = fieldEl.querySelector(
          'input[name="dob_day"]'
        ) as HTMLInputElement | null;
        const yearInput = fieldEl.querySelector(
          'input[name="dob_year"]'
        ) as HTMLInputElement | null;
        const inputs = [monthInput, dayInput, yearInput].filter(
          (input): input is HTMLInputElement => Boolean(input)
        );
        const calendarButton = fieldEl.querySelector(
          ".dob-calendar-btn"
        ) as HTMLButtonElement | null;
        const labelEl = fieldEl.querySelector("label") as HTMLElement | null;
        const ageEl = fieldEl.querySelector(".dob-age") as HTMLElement | null;

        const updateState = () => {
          const hasValue = inputs.some((input) => input.value.trim().length > 0);
          const isFocused = inputs.some((input) => document.activeElement === input);
          if (hasValue || isFocused) {
            fieldEl.classList.add("is-active");
          } else {
            fieldEl.classList.remove("is-active");
          }
        };

        const sanitizeInput = (input: HTMLInputElement, maxLen: number) => {
          const digitsOnly = input.value.replace(/\D/g, "");
          if (digitsOnly !== input.value) {
            input.value = digitsOnly;
          }
          if (input.value.length > maxLen) {
            input.value = input.value.slice(0, maxLen);
          }
        };

        const clearAgeTimer = () => {
          const timerId = Number(fieldEl.dataset.dobAgeTimer || "0");
          if (timerId) {
            window.clearInterval(timerId);
            fieldEl.dataset.dobAgeTimer = "";
          }
        };

        const ensureAgeTimer = () => {
          if (fieldEl.dataset.dobAgeTimer) return;
          const timerId = window.setInterval(() => {
            updateAge();
          }, 1000);
          fieldEl.dataset.dobAgeTimer = String(timerId);
        };

        const formatAge = (dobDate: Date) => {
          const now = new Date();
          let years = now.getFullYear() - dobDate.getFullYear();
          const anniversary = new Date(dobDate);
          anniversary.setFullYear(dobDate.getFullYear() + years);
          if (anniversary > now) {
            years -= 1;
            anniversary.setFullYear(dobDate.getFullYear() + years);
          }
          let months = now.getMonth() - anniversary.getMonth();
          let monthAnchor = new Date(anniversary);
          if (months < 0) {
            months += 12;
          }
          monthAnchor.setMonth(anniversary.getMonth() + months);
          if (monthAnchor > now) {
            months -= 1;
            monthAnchor = new Date(anniversary);
            monthAnchor.setMonth(anniversary.getMonth() + months);
          }
          if (months < 0) {
            months += 12;
            years = Math.max(0, years - 1);
            monthAnchor = new Date(anniversary);
            monthAnchor.setMonth(anniversary.getMonth() + months);
          }
          const msDiff = now.getTime() - monthAnchor.getTime();
          const days = Math.max(0, Math.floor(msDiff / (1000 * 60 * 60 * 24)));
          const totalSeconds = Math.max(
            0,
            Math.floor((now.getTime() - dobDate.getTime()) / 1000)
          );
          const hours = Math.floor((totalSeconds % 86400) / 3600);
          const minutes = Math.floor((totalSeconds % 3600) / 60);
          const seconds = totalSeconds % 60;
          return `${years} YEARS ${months} MONTHS ${days} DAYS ${hours} HOURS ${minutes} MINUTES ${seconds} SECONDS`;
        };

        const updateAge = () => {
          if (!ageEl || !labelEl) return;
          const month = monthInput?.value.trim() || "";
          const day = dayInput?.value.trim() || "";
          const year = yearInput?.value.trim() || "";
          if (month.length < 2 || day.length < 2 || year.length < 4) {
            clearAgeTimer();
            labelEl.textContent = "DATE OF BIRTH";
            ageEl.textContent = "";
            fieldEl.classList.remove("age-active");
            return;
          }
          const parsedDob = parseDobParts(month, day, year);
          if (!parsedDob.valid || !parsedDob.date) {
            clearAgeTimer();
            labelEl.textContent = "DATE OF BIRTH";
            ageEl.textContent = "PLEASE PUT REAL DATE.";
            fieldEl.classList.add("age-active");
            return;
          }
          const dobDate = parsedDob.date;
          labelEl.textContent = "YOU HAVE BEEN ALIVE FOR";
          ageEl.textContent = formatAge(dobDate);
          fieldEl.classList.add("age-active");
          ensureAgeTimer();
        };

        inputs.forEach((input, index) => {
          const maxLen = Number(input.getAttribute("maxlength") || "0");
          input.addEventListener("input", () => {
            sanitizeInput(input, maxLen);
            if (maxLen > 0 && input.value.length === maxLen && index < inputs.length - 1) {
              inputs[index + 1].focus();
            }
            updateState();
            updateAge();
          });
          input.addEventListener("keydown", (event) => {
            if (event.key === "Backspace" && input.value === "" && index > 0) {
              inputs[index - 1].focus();
            }
          });
          input.addEventListener("focus", updateState);
          input.addEventListener("blur", () => {
            setTimeout(updateState, 0);
          });
        });

        const monthNames = [
          "January",
          "February",
          "March",
          "April",
          "May",
          "June",
          "July",
          "August",
          "September",
          "October",
          "November",
          "December",
        ];

        const ensureCalendar = () => {
          let calendar = fieldEl.querySelector(".dob-calendar") as HTMLElement | null;
          if (calendar) return calendar;
          calendar = document.createElement("div");
          calendar.className = "dob-calendar";
          calendar.innerHTML = `
            <div class="dob-calendar-header">
              <button type="button" class="dob-calendar-nav prev" aria-label="Previous month">‹</button>
              <div class="dob-calendar-title">
                <span class="dob-calendar-title-month"></span>
                <button type="button" class="dob-calendar-title-year" aria-label="Choose year"></button>
              </div>
              <button type="button" class="dob-calendar-nav next" aria-label="Next month">›</button>
            </div>
            <div class="dob-calendar-controls">
              <select class="dob-calendar-month" aria-label="Select month">
                ${monthNames
                  .map((name, index) => `<option value="${index}">${name}</option>`)
                  .join("")}
              </select>
              <select class="dob-calendar-year" aria-label="Select year">
                ${Array.from({ length: 3001 }, (_, i) => 1000 + i)
                  .map((year) => `<option value="${year}">${year}</option>`)
                  .join("")}
              </select>
            </div>
            <div class="dob-calendar-weekdays">
              <span>Su</span><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span>
            </div>
            <div class="dob-calendar-grid"></div>
            <div class="dob-calendar-years">
              <div class="dob-calendar-years-header">
                <button type="button" class="dob-calendar-years-prev" aria-label="Previous years">‹</button>
                <div class="dob-calendar-years-title"></div>
                <button type="button" class="dob-calendar-years-next" aria-label="Next years">›</button>
              </div>
              <div class="dob-calendar-years-grid"></div>
            </div>
          `;
          fieldEl.appendChild(calendar);
          return calendar;
        };

        const getSelectedDate = () => {
          const month = monthInput ? parseInt(monthInput.value, 10) : NaN;
          const day = dayInput ? parseInt(dayInput.value, 10) : NaN;
          const year = yearInput ? parseInt(yearInput.value, 10) : NaN;
          if (!Number.isNaN(month) && !Number.isNaN(day) && !Number.isNaN(year)) {
            return new Date(year, month - 1, day);
          }
          return new Date();
        };

        const fillDate = (date: Date) => {
          if (!monthInput || !dayInput || !yearInput) return;
          monthInput.value = String(date.getMonth() + 1).padStart(2, "0");
          dayInput.value = String(date.getDate()).padStart(2, "0");
          yearInput.value = String(date.getFullYear());
          updateState();
          updateAge();
        };

        const openCalendar = () => {
          const calendar = ensureCalendar();
          const title = calendar.querySelector(".dob-calendar-title") as HTMLElement | null;
          const titleMonth = calendar.querySelector(
            ".dob-calendar-title-month"
          ) as HTMLElement | null;
          const titleYearButton = calendar.querySelector(
            ".dob-calendar-title-year"
          ) as HTMLButtonElement | null;
          const grid = calendar.querySelector(".dob-calendar-grid") as HTMLElement | null;
          const yearsPanel = calendar.querySelector(".dob-calendar-years") as HTMLElement | null;
          const yearsTitle = calendar.querySelector(
            ".dob-calendar-years-title"
          ) as HTMLElement | null;
          const yearsGrid = calendar.querySelector(
            ".dob-calendar-years-grid"
          ) as HTMLElement | null;
          const yearsPrev = calendar.querySelector(
            ".dob-calendar-years-prev"
          ) as HTMLButtonElement | null;
          const yearsNext = calendar.querySelector(
            ".dob-calendar-years-next"
          ) as HTMLButtonElement | null;
          const monthSelect = calendar.querySelector(
            ".dob-calendar-month"
          ) as HTMLSelectElement | null;
          const yearSelect = calendar.querySelector(
            ".dob-calendar-year"
          ) as HTMLSelectElement | null;
          if (
            !title ||
            !titleMonth ||
            !titleYearButton ||
            !grid ||
            !yearsPanel ||
            !yearsTitle ||
            !yearsGrid ||
            !yearsPrev ||
            !yearsNext ||
            !monthSelect ||
            !yearSelect
          )
            return;
          const selected = getSelectedDate();
          let viewYear = selected.getFullYear();
          let viewMonth = selected.getMonth();
          if (viewYear < 1000) viewYear = 1000;
          if (viewYear > 4000) viewYear = 4000;
          const yearsPerPage = 12;
          const clampYearStart = (start: number) => {
            let value = start;
            if (value < 1000) value = 1000;
            if (value > 4000 - (yearsPerPage - 1)) {
              value = 4000 - (yearsPerPage - 1);
            }
            return value;
          };
          let yearsStart = clampYearStart(
            Math.floor(viewYear / yearsPerPage) * yearsPerPage
          );

          const renderCalendar = () => {
            titleMonth.textContent = monthNames[viewMonth];
            titleYearButton.textContent = String(viewYear);
            monthSelect.value = String(viewMonth);
            yearSelect.value = String(viewYear);
            grid.innerHTML = "";
            const firstDay = new Date(viewYear, viewMonth, 1).getDay();
            const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
            for (let i = 0; i < firstDay; i += 1) {
              const empty = document.createElement("span");
              empty.className = "dob-calendar-empty";
              grid.appendChild(empty);
            }
            for (let day = 1; day <= daysInMonth; day += 1) {
              const button = document.createElement("button");
              button.type = "button";
              button.className = "dob-calendar-day";
              if (
                day === selected.getDate() &&
                viewMonth === selected.getMonth() &&
                viewYear === selected.getFullYear()
              ) {
                button.classList.add("selected");
              }
              button.textContent = String(day);
              button.dataset.day = String(day);
              grid.appendChild(button);
            }
          };

          const renderYears = () => {
            yearsStart = clampYearStart(yearsStart);
            yearsTitle.textContent = `${yearsStart} - ${yearsStart + (yearsPerPage - 1)}`;
            yearsGrid.innerHTML = "";
            for (let i = 0; i < yearsPerPage; i += 1) {
              const yearValue = yearsStart + i;
              const button = document.createElement("button");
              button.type = "button";
              button.className = "dob-calendar-year-btn";
              button.textContent = String(yearValue);
              button.dataset.year = String(yearValue);
              if (yearValue === viewYear) {
                button.classList.add("selected");
              }
              yearsGrid.appendChild(button);
            }
          };

          const openYears = () => {
            calendar.classList.add("years-open");
            yearsStart = clampYearStart(
              Math.floor(viewYear / yearsPerPage) * yearsPerPage
            );
            renderYears();
          };

          const closeYears = () => {
            calendar.classList.remove("years-open");
          };

          const handleCalendarClick = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            if (target.closest(".dob-calendar-nav.prev")) {
              viewMonth -= 1;
              if (viewMonth < 0) {
                viewMonth = 11;
                viewYear = Math.max(1000, viewYear - 1);
              }
              renderCalendar();
              return;
            }
            if (target.closest(".dob-calendar-nav.next")) {
              viewMonth += 1;
              if (viewMonth > 11) {
                viewMonth = 0;
                viewYear = Math.min(4000, viewYear + 1);
              }
              renderCalendar();
              return;
            }
            if (target.closest(".dob-calendar-years-prev")) {
              yearsStart = clampYearStart(yearsStart - yearsPerPage);
              renderYears();
              return;
            }
            if (target.closest(".dob-calendar-years-next")) {
              yearsStart = clampYearStart(yearsStart + yearsPerPage);
              renderYears();
              return;
            }
            if (target.classList.contains("dob-calendar-year-btn")) {
              const yearValue = Number(target.dataset.year || "0");
              if (yearValue >= 1000 && yearValue <= 4000) {
                viewYear = yearValue;
                closeYears();
                renderCalendar();
              }
              return;
            }
            if (target.classList.contains("dob-calendar-month")) {
              viewMonth = Number((target as HTMLSelectElement).value);
              renderCalendar();
              return;
            }
            if (target.classList.contains("dob-calendar-year")) {
              viewYear = Number((target as HTMLSelectElement).value);
              renderCalendar();
              return;
            }
            if (target.classList.contains("dob-calendar-day")) {
              const day = Number(target.dataset.day || "0");
              if (day > 0) {
                fillDate(new Date(viewYear, viewMonth, day));
              }
              closeCalendar();
            }
          };

          const handleOutsideClick = (event: MouseEvent) => {
            const target = event.target as Node;
            if (!calendar.contains(target) && !fieldEl.contains(target)) {
              closeCalendar();
            }
          };

          const handleEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
              closeCalendar();
            }
          };

          const handleMonthChange = (event: Event) => {
            const target = event.target as HTMLSelectElement;
            viewMonth = Number(target.value);
            renderCalendar();
          };
          const handleYearChange = (event: Event) => {
            const target = event.target as HTMLSelectElement;
            viewYear = Number(target.value);
            renderCalendar();
          };
          const handleYearTitleClick = () => {
            if (calendar.classList.contains("years-open")) {
              closeYears();
            } else {
              openYears();
            }
          };

          const closeCalendar = () => {
            calendar.classList.remove("open");
            closeYears();
            calendar.removeEventListener("click", handleCalendarClick);
            monthSelect.removeEventListener("change", handleMonthChange);
            yearSelect.removeEventListener("change", handleYearChange);
            titleYearButton.removeEventListener("click", handleYearTitleClick);
            document.removeEventListener("mousedown", handleOutsideClick);
            document.removeEventListener("keydown", handleEscape);
          };

          calendar.classList.add("open");
          (calendar as any)._closeDobCalendar = closeCalendar;
          renderCalendar();
          calendar.addEventListener("click", handleCalendarClick);
          monthSelect.addEventListener("change", handleMonthChange);
          yearSelect.addEventListener("change", handleYearChange);
          titleYearButton.addEventListener("click", handleYearTitleClick);
          setTimeout(() => {
            document.addEventListener("mousedown", handleOutsideClick);
            document.addEventListener("keydown", handleEscape);
          }, 0);
        };

        calendarButton?.addEventListener("click", () => {
          const calendar = ensureCalendar();
          if (calendar.classList.contains("open")) {
            const close = (calendar as any)._closeDobCalendar as (() => void) | undefined;
            if (close) {
              close();
            } else {
              calendar.classList.remove("open");
            }
            return;
          }
          openCalendar();
        });

        updateState();
        updateAge();
      });
    };

    const bindFormActions = (container: Element | null) => {
      if (!container) return;
      const form = container.querySelector("form");
      if (form && form.getAttribute("data-bound") === "true") return;
      if (form) form.setAttribute("data-bound", "true");
      setupDobFields(container);
      const moduleR = container.querySelector('[data-form="module-r"]') as HTMLElement | null;
      if (moduleR && moduleR.getAttribute("data-bound") !== "true") {
        moduleR.setAttribute("data-bound", "true");
        const positioningRoot = moduleR.querySelector(
          "[data-positioning-root]"
        ) as HTMLElement | null;
        if (positioningRoot && positioningRoot.getAttribute("data-mounted") !== "true") {
          const root = createRoot(positioningRoot);
          root.render(<PositioningModule />);
          positioningRoot.setAttribute("data-mounted", "true");
        }
        const widthInput = moduleR.querySelector('input[name="global_width"]') as
          | HTMLInputElement
          | null;
        const lockBtn = moduleR.querySelector('[data-action="lock-width"]') as
          | HTMLButtonElement
          | null;
        const resetBtn = moduleR.querySelector('[data-action="reset-width"]') as
          | HTMLButtonElement
          | null;
        const manualBtn = moduleR.querySelector('[data-action="mode-manual"]') as
          | HTMLButtonElement
          | null;
        const autoBtn = moduleR.querySelector('[data-action="mode-auto"]') as
          | HTMLButtonElement
          | null;
        const backInitBtn = moduleR.querySelector('[data-action="back-init"]') as
          | HTMLButtonElement
          | null;
        const backEntryBtn = moduleR.querySelectorAll('[data-action="back-entry"]');
        const cardBody = moduleR.querySelector('[data-card="body"]') as HTMLElement | null;
        const cardNose = moduleR.querySelector('[data-card="nose"]') as HTMLElement | null;
        const cardFins = moduleR.querySelector('[data-card="fins"]') as HTMLElement | null;
        const cardPositioning = moduleR.querySelector('[data-card="positioning"]') as
          | HTMLElement
          | null;
        const backManualBtns = moduleR.querySelectorAll('[data-action="back-manual"]');
        const markBodyBtn = moduleR.querySelector('[data-action="mark-body"]') as
          | HTMLButtonElement
          | null;
        const unmarkBodyBtn = moduleR.querySelector('[data-action="unmark-body"]') as
          | HTMLButtonElement
          | null;
        const markNoseBtn = moduleR.querySelector('[data-action="mark-nose"]') as
          | HTMLButtonElement
          | null;
        const unmarkNoseBtn = moduleR.querySelector('[data-action="unmark-nose"]') as
          | HTMLButtonElement
          | null;
        const markFinsBtn = moduleR.querySelector('[data-action="mark-fins"]') as
          | HTMLButtonElement
          | null;
        const unmarkFinsBtn = moduleR.querySelector('[data-action="unmark-fins"]') as
          | HTMLButtonElement
          | null;
        const saveNoseBtn = moduleR.querySelector('[data-action="save-nose"]') as
          | HTMLButtonElement
          | null;
        const finsNextBtn = moduleR.querySelector('[data-action="fins-next"]') as
          | HTMLButtonElement
          | null;
        const finsClearIndex = moduleR.querySelector('[data-action="clear-fins-index"]') as
          | HTMLButtonElement
          | null;
        const finsSaveBtn = moduleR.querySelector('[data-action="fins-save"]') as
          | HTMLButtonElement
          | null;
        const backFinsBtn = moduleR.querySelector('[data-action="back-fins"]') as
          | HTMLButtonElement
          | null;
        const finsCountInput = moduleR.querySelector('input[name="fin_set_count"]') as
          | HTMLInputElement
          | null;
        const finsList = moduleR.querySelector(".module-r-fins-list") as HTMLElement | null;
        const storageList = moduleR.querySelector(".module-r-storage-list") as HTMLElement | null;
        const workspaceDrop = moduleR.querySelector(
          ".module-r-workspace-drop"
        ) as HTMLElement | null;
        const savePositioningBtn = moduleR.querySelector('[data-action="save-positioning"]') as
          | HTMLButtonElement
          | null;
        const openMotorMounts = moduleR.querySelector('[data-action="open-motor-mounts"]') as
          | HTMLElement
          | null;
        const openAdditionalTubes = moduleR.querySelector('[data-action="open-additional-tubes"]') as
          | HTMLElement
          | null;
        const openBulkheads = moduleR.querySelector('[data-action="open-bulkheads"]') as
          | HTMLElement
          | null;
        const clearBodyBtn = moduleR.querySelector('[data-action="clear-body"]') as
          | HTMLButtonElement
          | null;
        const backBodyBtns = moduleR.querySelectorAll('[data-action="back-body"]');
        const motorMountsNext = moduleR.querySelector('[data-action="motor-mounts-next"]') as
          | HTMLButtonElement
          | null;
        const motorMountsClearIndex = moduleR.querySelector(
          '[data-action="motor-mounts-clear-index"]'
        ) as HTMLButtonElement | null;
        const motorMountsSave = moduleR.querySelector('[data-action="motor-mounts-save"]') as
          | HTMLButtonElement
          | null;
        const motorMountsClear = moduleR.querySelector('[data-action="motor-mounts-clear"]') as
          | HTMLButtonElement
          | null;
        const backMotorMounts = moduleR.querySelector('[data-action="back-motor-mounts"]') as
          | HTMLButtonElement
          | null;
        const additionalNext = moduleR.querySelector('[data-action="additional-next"]') as
          | HTMLButtonElement
          | null;
        const additionalSave = moduleR.querySelector('[data-action="additional-save"]') as
          | HTMLButtonElement
          | null;
        const additionalClear = moduleR.querySelector('[data-action="additional-clear"]') as
          | HTMLButtonElement
          | null;
        const additionalClearIndex = moduleR.querySelector(
          '[data-action="additional-clear-index"]'
        ) as HTMLButtonElement | null;
        const backAdditional = moduleR.querySelector('[data-action="back-additional"]') as
          | HTMLButtonElement
          | null;
        const bulkheadNext = moduleR.querySelector('[data-action="bulkheads-next"]') as
          | HTMLButtonElement
          | null;
        const bulkheadsSave = moduleR.querySelector('[data-action="bulkheads-save"]') as
          | HTMLButtonElement
          | null;
        const bulkheadsClear = moduleR.querySelector('[data-action="bulkheads-clear"]') as
          | HTMLButtonElement
          | null;
        const bulkheadsClearIndex = moduleR.querySelector(
          '[data-action="bulkheads-clear-index"]'
        ) as HTMLButtonElement | null;
        const backBulkheads = moduleR.querySelector('[data-action="back-bulkheads"]') as
          | HTMLButtonElement
          | null;
        const stageCountInput = moduleR.querySelector('input[name="stage_count_manual"]') as
          | HTMLInputElement
          | null;
        const stageList = moduleR.querySelector(".module-r-stage-list") as HTMLElement | null;
        const additionalCountInput = moduleR.querySelector(
          'input[name="additional_tube_count"]'
        ) as HTMLInputElement | null;
        const additionalList = moduleR.querySelector(".module-r-additional-list") as
          | HTMLElement
          | null;
        const bulkheadCountInput = moduleR.querySelector('input[name="bulkhead_count"]') as
          | HTMLInputElement
          | null;
        const bulkheadList = moduleR.querySelector(".module-r-bulkhead-list") as HTMLElement | null;
        const savedStageCount = Number(window.localStorage.getItem("arx_module_r_stage_count") || "0");
        if (stageCountInput && Number.isFinite(savedStageCount) && savedStageCount > 0) {
          stageCountInput.value = String(savedStageCount);
        }
        const savedBulkheadCount = Number(
          window.localStorage.getItem("arx_module_r_bulkhead_count") || "0"
        );
        if (bulkheadCountInput && Number.isFinite(savedBulkheadCount) && savedBulkheadCount > 0) {
          bulkheadCountInput.value = String(savedBulkheadCount);
        }
        const savedAdditionalCount = Number(
          window.localStorage.getItem("arx_module_r_additional_count") || "0"
        );
        if (
          additionalCountInput &&
          Number.isFinite(savedAdditionalCount) &&
          savedAdditionalCount >= 0
        ) {
          additionalCountInput.value = String(savedAdditionalCount);
        }
        const noseClearBtn = moduleR.querySelector('[data-action="clear-nose"]') as
          | HTMLButtonElement
          | null;
        const finsClearBtn = moduleR.querySelector('[data-action="clear-fins"]') as
          | HTMLButtonElement
          | null;
        const pages = moduleR.querySelectorAll("[data-page]");
        const currentPage = () => String(moduleR.getAttribute("data-active-page") || "init");
        const enhanceModuleRSelects = () => {
          const closeAll = () => {
            moduleR
              .querySelectorAll(".module-r-custom-select.is-open")
              .forEach((node) => {
                const wrapper = node as HTMLElement;
                wrapper.classList.remove("is-open");
                const trigger = wrapper.querySelector(
                  ".module-r-custom-select-trigger"
                ) as HTMLButtonElement | null;
                const active = wrapper.querySelectorAll(".module-r-custom-select-option.is-active");
                active.forEach((item) => (item as HTMLElement).classList.remove("is-active"));
                if (trigger) {
                  trigger.setAttribute("aria-expanded", "false");
                }
              });
          };
          if (moduleR.getAttribute("data-custom-select-bound") !== "true") {
            moduleR.setAttribute("data-custom-select-bound", "true");
            document.addEventListener("pointerdown", (event) => {
              const target = event.target as Node | null;
              if (!target || !moduleR.contains(target)) {
                closeAll();
                return;
              }
              if (!(target as Element).closest(".module-r-custom-select")) {
                closeAll();
              }
            });
          }

          const selects = Array.from(moduleR.querySelectorAll("select")) as HTMLSelectElement[];
          selects.forEach((select) => {
            if (select.classList.contains("module-r-select-native-hidden")) return;

            const host = select.parentElement;
            if (!host) return;

            const wrapper = document.createElement("div");
            wrapper.className = "module-r-custom-select";

            const trigger = document.createElement("button");
            trigger.type = "button";
            trigger.className = "module-r-custom-select-trigger";
            trigger.setAttribute("aria-haspopup", "listbox");
            trigger.setAttribute("aria-expanded", "false");

            const menu = document.createElement("div");
            menu.className = "module-r-custom-select-menu";
            menu.tabIndex = -1;
            menu.setAttribute("role", "listbox");

            const syncFromNative = () => {
              const current = select.options[select.selectedIndex];
              trigger.textContent = current?.textContent || "Select";
              Array.from(menu.querySelectorAll(".module-r-custom-select-option")).forEach((node) => {
                const el = node as HTMLButtonElement;
                const selected = el.getAttribute("data-value") === select.value;
                el.classList.toggle("is-selected", selected);
                if (selected) el.setAttribute("aria-selected", "true");
                else el.removeAttribute("aria-selected");
              });
            };
            const optionButtons: HTMLButtonElement[] = [];
            let activeIndex = -1;
            const getEnabledButtons = () => optionButtons.filter((btn) => !btn.disabled);
            const setActiveOption = (btn: HTMLButtonElement | null) => {
              optionButtons.forEach((node) => node.classList.remove("is-active"));
              if (!btn) {
                activeIndex = -1;
                return;
              }
              activeIndex = optionButtons.indexOf(btn);
              btn.classList.add("is-active");
              btn.scrollIntoView({ block: "nearest" });
            };
            const focusSelectedOrFirst = () => {
              const selectedBtn =
                (optionButtons.find((btn) => btn.getAttribute("data-value") === select.value) as
                  | HTMLButtonElement
                  | undefined) || null;
              const target = selectedBtn || getEnabledButtons()[0] || null;
              setActiveOption(target);
            };
            const openMenu = (preferLast = false) => {
              closeAll();
              const rect = trigger.getBoundingClientRect();
              const viewportH = window.innerHeight || 0;
              const menuMax = Math.min(260, viewportH * 0.34);
              const expectedMenuH = Math.min(
                Math.max(menu.scrollHeight, optionButtons.length * 34, 60),
                menuMax
              );
              const spaceBelow = viewportH - rect.bottom;
              const spaceAbove = rect.top;
              const openUp = spaceBelow < expectedMenuH + 12 && spaceAbove > spaceBelow;
              wrapper.classList.toggle("open-up", openUp);
              wrapper.classList.add("is-open");
              trigger.setAttribute("aria-expanded", "true");
              if (preferLast) {
                const enabled = getEnabledButtons();
                setActiveOption(enabled[enabled.length - 1] || null);
              } else {
                focusSelectedOrFirst();
              }
              menu.focus();
            };
            const closeMenu = () => {
              wrapper.classList.remove("is-open");
              wrapper.classList.remove("open-up");
              trigger.setAttribute("aria-expanded", "false");
              setActiveOption(null);
            };
            const moveActive = (step: number) => {
              const enabled = getEnabledButtons();
              if (!enabled.length) return;
              const currentBtn =
                activeIndex >= 0 ? optionButtons[activeIndex] : (null as HTMLButtonElement | null);
              const currentEnabledIdx = currentBtn ? enabled.indexOf(currentBtn) : -1;
              const nextEnabledIdx = Math.max(
                0,
                Math.min(enabled.length - 1, currentEnabledIdx + step)
              );
              setActiveOption(enabled[nextEnabledIdx]);
            };
            const commitActive = () => {
              if (activeIndex < 0) return;
              const btn = optionButtons[activeIndex];
              if (!btn || btn.disabled) return;
              btn.click();
            };

            Array.from(select.options).forEach((opt) => {
              const optionBtn = document.createElement("button");
              optionBtn.type = "button";
              optionBtn.className = "module-r-custom-select-option";
              optionBtn.textContent = opt.textContent || opt.value;
              optionBtn.setAttribute("data-value", opt.value);
              optionBtn.disabled = Boolean(opt.disabled);
              optionBtn.setAttribute("role", "option");
              optionBtn.addEventListener("click", () => {
                select.value = opt.value;
                syncFromNative();
                closeMenu();
                trigger.focus();
                select.dispatchEvent(new Event("input", { bubbles: true }));
                select.dispatchEvent(new Event("change", { bubbles: true }));
              });
              optionBtn.addEventListener("mouseenter", () => {
                setActiveOption(optionBtn);
              });
              optionButtons.push(optionBtn);
              menu.appendChild(optionBtn);
            });

            trigger.addEventListener("click", (event) => {
              event.preventDefault();
              const isOpen = wrapper.classList.contains("is-open");
              if (isOpen) closeMenu();
              else openMenu();
            });
            trigger.addEventListener("keydown", (event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                if (!wrapper.classList.contains("is-open")) openMenu();
                else moveActive(1);
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                if (!wrapper.classList.contains("is-open")) openMenu(true);
                else moveActive(-1);
                return;
              }
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (!wrapper.classList.contains("is-open")) openMenu();
                else commitActive();
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closeMenu();
              }
            });
            menu.addEventListener("keydown", (event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                moveActive(1);
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                moveActive(-1);
                return;
              }
              if (event.key === "Home") {
                event.preventDefault();
                const first = getEnabledButtons()[0] || null;
                setActiveOption(first);
                return;
              }
              if (event.key === "End") {
                event.preventDefault();
                const enabled = getEnabledButtons();
                setActiveOption(enabled[enabled.length - 1] || null);
                return;
              }
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                commitActive();
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closeMenu();
                trigger.focus();
                return;
              }
              if (event.key === "Tab") {
                closeMenu();
              }
            });

            select.classList.add("module-r-select-native-hidden");
            host.insertBefore(wrapper, select);
            wrapper.appendChild(trigger);
            wrapper.appendChild(menu);
            wrapper.appendChild(select);
            select.addEventListener("change", syncFromNative);
            syncFromNative();
          });
        };
        const showPage = (page: string) => {
          moduleR
            .querySelectorAll(".module-r-custom-select.is-open")
            .forEach((node) => {
              const wrapper = node as HTMLElement;
              wrapper.classList.remove("is-open", "open-up");
              const trigger = wrapper.querySelector(
                ".module-r-custom-select-trigger"
              ) as HTMLButtonElement | null;
              trigger?.setAttribute("aria-expanded", "false");
            });
          pages.forEach((node) => {
            const el = node as HTMLElement;
            el.style.display = el.getAttribute("data-page") === page ? "grid" : "none";
            if (el.getAttribute("data-page") === page) {
              el.scrollTop = 0;
            }
          });
          const parachuteModal = moduleR.querySelector(".module-r-parachute-modal") as
            | HTMLElement
            | null;
          if (parachuteModal) {
            parachuteModal.removeAttribute("data-open");
            parachuteModal.removeAttribute("data-target-component-id");
            parachuteModal.remove();
          }
          moduleR.setAttribute("data-active-page", page);
          moduleR.scrollTop = 0;
          enhanceModuleRSelects();
        };
        const autoPage = moduleR.querySelector('[data-page="auto"]') as HTMLElement | null;
        const submitAuto = moduleR.querySelector('[data-action="submit-auto"]') as
          | HTMLButtonElement
          | null;
        const pickRicBtn = moduleR.querySelector('[data-action="pick-ric"]') as
          | HTMLButtonElement
          | null;
        const ricInput = moduleR.querySelector('input[name="ric_file"]') as
          | HTMLInputElement
          | null;
        const ricName = moduleR.querySelector(".module-r-file-name") as HTMLElement | null;
        const statusEl = moduleR.querySelector(".form-status") as HTMLElement | null;
        const autoResultsEl = moduleR.querySelector(".module-r-auto-results") as HTMLElement | null;

        const setStatus = (message: string) => {
          const statuses = moduleR.querySelectorAll(".form-status");
          statuses.forEach((el) => {
            (el as HTMLElement).textContent = message;
          });
          if (!statuses.length && statusEl) {
            statusEl.textContent = message;
          }
        };
        const ensureParachuteModal = () => {
          let modal = moduleR.querySelector(".module-r-parachute-modal") as HTMLElement | null;
          if (modal) return modal;
          modal = document.createElement("div");
          modal.className = "module-r-parachute-modal";
          modal.innerHTML = `
            <div class="module-r-parachute-modal-backdrop" data-action="close-parachute-modal"></div>
            <div class="module-r-parachute-modal-panel" role="dialog" aria-modal="true" aria-label="Parachute Library">
              <div class="panel-header">PARACHUTE LIBRARY</div>
              <div class="form-status">Source: ${MODULE_R_PARACHUTE_LIBRARY_URL}</div>
              <div class="module-r-parachute-list">
                <div class="arx-field">
                  <select data-field="parachute_modal_select">
                    ${MODULE_R_PARACHUTE_LIBRARY.map(
                      (item) =>
                        `<option value="${item.id}">${item.name} | ${item.mass_lb.toFixed(2)} lb | Cd ${item.drag_coefficient.toFixed(2)} | ${item.material}</option>`
                    ).join("")}
                  </select>
                  <label>PARACHUTE MODEL</label>
                </div>
                <div class="module-r-parachute-meta" data-parachute-meta></div>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="apply-parachute-modal">Apply</button>
                <button type="button" class="arx-btn" data-action="close-parachute-modal">Close</button>
              </div>
            </div>
          `;
          moduleR.appendChild(modal);
          const select = modal.querySelector('select[data-field="parachute_modal_select"]') as
            | HTMLSelectElement
            | null;
          const syncMeta = () => {
            const meta = modal?.querySelector("[data-parachute-meta]") as HTMLElement | null;
            if (!meta || !select) return;
            const selected = MODULE_R_PARACHUTE_LIBRARY.find((item) => item.id === select.value);
            if (!selected) {
              meta.textContent = "";
              return;
            }
            meta.textContent = `MASS ${selected.mass_lb.toFixed(2)} LB  |  DRAG ${selected.drag_coefficient.toFixed(2)}  |  MATERIAL ${selected.material}`;
          };
          if (select) {
            select.addEventListener("change", syncMeta);
            syncMeta();
          }
          enhanceModuleRSelects();
          return modal;
        };
        const openParachuteModal = (componentNode: HTMLElement) => {
          const modal = ensureParachuteModal();
          modal.setAttribute("data-open", "true");
          modal.setAttribute("data-target-component-id", componentNode.getAttribute("data-component-id") || "");
          const select = modal.querySelector('select[data-field="parachute_modal_select"]') as
            | HTMLSelectElement
            | null;
          const existing = String(componentNode.getAttribute("data-parachute-id") || "");
          if (select && existing) {
            select.value = existing;
            select.dispatchEvent(new Event("change", { bubbles: true }));
          }
        };
        const closeParachuteModal = () => {
          const modal = moduleR.querySelector(".module-r-parachute-modal") as HTMLElement | null;
          if (!modal) return;
          modal.removeAttribute("data-open");
          modal.removeAttribute("data-target-component-id");
          // Remove the node to prevent leaked custom-select UI fragments across pages.
          modal.remove();
        };
        const applyParachuteSelectionToComponent = (component: HTMLElement, parachuteId: string) => {
          const selected = MODULE_R_PARACHUTE_LIBRARY.find((item) => item.id === parachuteId);
          if (!selected) return;
          const nameInput = component.querySelector('input[data-field="name"]') as HTMLInputElement | null;
          const massInput = component.querySelector('input[data-field="mass"]') as HTMLInputElement | null;
          const dragInput = component.querySelector('input[data-field="drag"]') as HTMLInputElement | null;
          const materialInput = component.querySelector('input[data-field="parachute_material"]') as
            | HTMLInputElement
            | null;
          const parachuteDisplay = component.querySelector(
            '[data-field="parachute_display"]'
          ) as HTMLInputElement | null;
          if (nameInput && !String(nameInput.value || "").trim()) {
            nameInput.value = selected.name;
          }
          if (massInput) massInput.value = selected.mass_lb.toFixed(2);
          if (dragInput) dragInput.value = selected.drag_coefficient.toFixed(3);
          if (materialInput) materialInput.value = selected.material;
          if (parachuteDisplay) parachuteDisplay.value = selected.name;
          component.setAttribute("data-parachute-id", selected.id);
          component.dispatchEvent(new Event("input", { bubbles: true }));
          component.dispatchEvent(new Event("change", { bubbles: true }));
        };
        const updateNosePreview = () => {
          const svg = moduleR.querySelector(
            `[data-nose-preview="main"]`
          ) as SVGSVGElement | null;
          const path = moduleR.querySelector(`[data-nose-shape="main"]`) as SVGPathElement | null;
          const lengthInput = moduleR.querySelector('input[name="nose_length_in"]') as
            | HTMLInputElement
            | null;
          const typeSelect = moduleR.querySelector('select[name="nose_type"]') as
            | HTMLSelectElement
            | null;
          if (!svg || !path) return;
          const noseLen = Math.max(0.1, Number(lengthInput?.value || 10));
          const type = String(typeSelect?.value || "OGIVE").toUpperCase();
          const h = 130;
          const x0 = 18;
          const centerY = h * 0.5;
          const L = Math.min(188, Math.max(58, noseLen * 8));
          const R = 24;
          const tipX = x0 + L;
          const samples = 56;
          const radiusAt = (x: number) => {
            const t = Math.max(0, Math.min(1, x / Math.max(L, 0.001)));
            if (type === "CONICAL") return R * (1 - t);
            if (type === "ELLIPTICAL") return R * Math.sqrt(Math.max(0, 1 - t * t));
            if (type === "PARABOLIC") return R * Math.max(0, 1 - t * t);
            const rho = (R * R + L * L) / (2 * R);
            // Tangent ogive profile: base radius at x=0 and smooth point at x=L.
            return (
              Math.sqrt(Math.max(0, rho * rho - x * x)) +
              R -
              rho
            );
          };
          const top: Array<{ x: number; y: number }> = [];
          for (let i = 0; i <= samples; i += 1) {
            const x = (L * i) / samples;
            const r = radiusAt(x);
            top.push({ x: x0 + x, y: centerY - r });
          }
          const bottom = top
            .slice(0, -1)
            .reverse()
            .map((p) => ({ x: p.x, y: centerY + (centerY - p.y) }));
          const d = [
            `M ${x0} ${centerY + R}`,
            ...top.map((p) => `L ${p.x} ${p.y}`),
            ...bottom.map((p) => `L ${p.x} ${p.y}`),
            "Z",
          ].join(" ");
          path.setAttribute("d", d);
        };
        const updateStagePreview = (index: number) => {
          if (!stageList) return;
          const path = stageList.querySelector(
            `[data-stage-shape="${index}"]`
          ) as SVGPathElement | null;
          if (!path) return;
          const getNum = (name: string, fallback: number) => {
            const input = stageList.querySelector(`input[name="${name}_${index}"]`) as
              | HTMLInputElement
              | null;
            const v = Number(input?.value ?? fallback);
            return Number.isFinite(v) && v > 0 ? v : fallback;
          };
          const length = getNum("stage_length", 20);
          const innerDiameter = getNum("inner_tube_diameter", 2);
          const innerThickness = getNum("inner_tube_thickness", 0.1);
          const width = 240;
          const height = 130;
          const pad = 14;
          const scaledLen = Math.min(200, Math.max(60, length * 4));
          const x0 = pad;
          const x1 = x0 + scaledLen;
          const bodyTop = 26;
          const bodyBottom = 104;
          const coreHeight = Math.min(
            bodyBottom - bodyTop - 10,
            Math.max(18, (innerDiameter - innerThickness * 2) * 8)
          );
          const coreTop = (height - coreHeight) / 2;
          const coreBottom = coreTop + coreHeight;
          const wall = Math.max(1.5, Math.min(12, innerThickness * 10));
          path.setAttribute(
            "d",
            `M ${x0} ${bodyBottom} L ${x1} ${bodyBottom} L ${x1} ${bodyTop} L ${x0} ${bodyTop} Z M ${x0 + 8} ${coreBottom} L ${
              x1 - 8
            } ${coreBottom} L ${x1 - 8} ${coreTop} L ${x0 + 8} ${coreTop} Z M ${x0} ${bodyBottom} L ${x0 + wall} ${bodyBottom} L ${
              x0 + wall
            } ${bodyTop} L ${x0} ${bodyTop} Z M ${x1 - wall} ${bodyBottom} L ${x1} ${bodyBottom} L ${x1} ${bodyTop} L ${
              x1 - wall
            } ${bodyTop} Z`
          );
        };
        const MODULE_R_TELEMETRY_MEDIA_DEFAULT = "/module-r/telemetry_transition.mp4";
        const MODULE_R_PARACHUTE_MEDIA_DEFAULT =
          "/@fs/Users/mehulverma422/.cursor/projects/Users-mehulverma422-Desktop-ArX-arx-os/assets/Screenshot_2026-02-12_at_6.38.51_PM-8ff42754-3b23-4ea8-959a-dadba5928638.png";
        const MODULE_R_MASS_MEDIA_DEFAULT =
          "/@fs/Users/mehulverma422/.cursor/projects/Users-mehulverma422-Desktop-ArX-arx-os/assets/Screenshot_2026-02-12_at_6.38.36_PM-97ff63be-7908-4a3e-9117-bb90cb653664.png";
        const updateAdditionalPreview = (tubeIndex: number) => {
          if (!additionalList) return;
          const svg = additionalList.querySelector(
            `[data-additional-preview="${tubeIndex}"]`
          ) as SVGSVGElement | null;
          const path = additionalList.querySelector(
            `[data-additional-shape="${tubeIndex}"]`
          ) as SVGPathElement | null;
          const telemetryLayer = additionalList.querySelector(
            `[data-additional-telemetry="${tubeIndex}"]`
          ) as SVGGElement | null;
          const parachuteLayer = additionalList.querySelector(
            `[data-additional-parachute-icon="${tubeIndex}"]`
          ) as SVGGElement | null;
          const massLayer = additionalList.querySelector(
            `[data-additional-mass-icon="${tubeIndex}"]`
          ) as SVGGElement | null;
          const telemetryVideo = additionalList.querySelector(
            `video[data-additional-telemetry-video="${tubeIndex}"]`
          ) as HTMLVideoElement | null;
          const parachuteImage = additionalList.querySelector(
            `img[data-additional-parachute-image="${tubeIndex}"]`
          ) as HTMLImageElement | null;
          const massImage = additionalList.querySelector(
            `img[data-additional-mass-image="${tubeIndex}"]`
          ) as HTMLImageElement | null;
          if (!path) return;
          const items = Array.from(
            additionalList.querySelectorAll(
              `.module-r-additional-components[data-tube="${tubeIndex}"] .module-r-additional-component`
            )
          ) as HTMLElement[];
          const width = 240;
          const height = 130;
          const pad = 12;
          const x0 = pad;
          const x1 = width - pad;
          const y0 = 8;
          const y1 = height - 6;
          const segments = Math.max(items.length, 1);
          const segW = (x1 - x0) / segments;
          let segmentPath = "";
          items.forEach((component, idx) => {
            const massInput = component.querySelector('input[data-field="mass"]') as
              | HTMLInputElement
              | null;
            const typeSelect = component.querySelector('select[data-field="type"]') as
              | HTMLSelectElement
              | null;
            const mass = Math.max(0, Number(massInput?.value || 0));
            const type = String(typeSelect?.value || "telemetry");
            const cx0 = x0 + idx * segW + 2;
            const cx1 = x0 + (idx + 1) * segW - 2;
            const maxH = y1 - y0 - 4;
            const h = Math.min(maxH, Math.max(6, mass * 8 + (type === "parachute" ? 4 : 0)));
            const cy0 = y1 - h - 2;
            if (type === "parachute") {
              const mid = (cx0 + cx1) * 0.5;
              segmentPath += ` M ${cx0} ${y1 - 2} Q ${mid} ${cy0 - 8} ${cx1} ${y1 - 2} L ${cx1} ${y1} L ${cx0} ${y1} Z`;
            } else {
              segmentPath += ` M ${cx0} ${y1 - 2} L ${cx1} ${y1 - 2} L ${cx1} ${cy0} L ${cx0} ${cy0} Z`;
            }
          });
          const hasTelemetry = items.some((component) => {
            const typeSelect = component.querySelector('select[data-field="type"]') as
              | HTMLSelectElement
              | null;
            return String(typeSelect?.value || "") === "telemetry";
          });
          const hasParachute = items.some((component) => {
            const typeSelect = component.querySelector('select[data-field="type"]') as
              | HTMLSelectElement
              | null;
            return String(typeSelect?.value || "") === "parachute";
          });
          const hasMass = items.some((component) => {
            const typeSelect = component.querySelector('select[data-field="type"]') as
              | HTMLSelectElement
              | null;
            return String(typeSelect?.value || "") === "mass";
          });

          const activeMedia = hasTelemetry ? "telemetry" : hasParachute ? "parachute" : hasMass ? "mass" : "none";
          if (svg) svg.setAttribute("data-telemetry-active", hasTelemetry ? "true" : "false");
          if (telemetryLayer) telemetryLayer.style.opacity = hasTelemetry ? "1" : "0";
          if (parachuteLayer) parachuteLayer.style.opacity = activeMedia === "parachute" ? "1" : "0";
          if (massLayer) massLayer.style.opacity = activeMedia === "mass" ? "1" : "0";

          const shellPath = `M ${x0} ${y1} L ${x1} ${y1} L ${x1} ${y0} L ${x0} ${y0} Z M ${
            x0 + 2
          } ${y1 - 2} Q ${(x0 + x1) * 0.5} ${y1 - 14} ${x1 - 2} ${y1 - 2} L ${x1 - 2} ${y1} L ${
            x0 + 2
          } ${y1} Z`;
          path.setAttribute("d", `${shellPath}${segmentPath}`);

          const telemetryMediaSrc =
            window.localStorage.getItem("arx_module_r_telemetry_media_url") ||
            MODULE_R_TELEMETRY_MEDIA_DEFAULT;
          const parachuteMediaSrc =
            window.localStorage.getItem("arx_module_r_parachute_media_url") ||
            MODULE_R_PARACHUTE_MEDIA_DEFAULT;
          const massMediaSrc =
            window.localStorage.getItem("arx_module_r_mass_media_url") || MODULE_R_MASS_MEDIA_DEFAULT;

          if (telemetryVideo) {
            if (telemetryVideo.getAttribute("data-src") !== telemetryMediaSrc) {
              telemetryVideo.setAttribute("data-src", telemetryMediaSrc);
              telemetryVideo.setAttribute("data-ready", "false");
              telemetryVideo.src = telemetryMediaSrc;
            }
            const ready =
              telemetryVideo.readyState >= 2 && telemetryVideo.networkState !== HTMLMediaElement.NETWORK_NO_SOURCE;
            telemetryVideo.setAttribute("data-ready", ready ? "true" : "false");
            telemetryVideo.setAttribute("data-active", activeMedia === "telemetry" ? "true" : "false");
            if (activeMedia === "telemetry" && ready) {
              const playPromise = telemetryVideo.play();
              if (playPromise && typeof playPromise.catch === "function") {
                playPromise.catch(() => undefined);
              }
            } else {
              telemetryVideo.pause();
            }
          }
          if (parachuteImage) {
            if (parachuteImage.getAttribute("data-src") !== parachuteMediaSrc) {
              parachuteImage.setAttribute("data-src", parachuteMediaSrc);
              parachuteImage.setAttribute("data-ready", "false");
              parachuteImage.src = parachuteMediaSrc;
            }
            const ready = Boolean(parachuteImage.complete && parachuteImage.naturalWidth > 0);
            parachuteImage.setAttribute("data-ready", ready ? "true" : "false");
            parachuteImage.setAttribute("data-active", activeMedia === "parachute" ? "true" : "false");
          }
          if (massImage) {
            if (massImage.getAttribute("data-src") !== massMediaSrc) {
              massImage.setAttribute("data-src", massMediaSrc);
              massImage.setAttribute("data-ready", "false");
              massImage.src = massMediaSrc;
            }
            const ready = Boolean(massImage.complete && massImage.naturalWidth > 0);
            massImage.setAttribute("data-ready", ready ? "true" : "false");
            massImage.setAttribute("data-active", activeMedia === "mass" ? "true" : "false");
          }
        };
        const updateBulkheadPreview = (index: number) => {
          if (!bulkheadList) return;
          const path = bulkheadList.querySelector(
            `[data-bulkhead-shape="${index}"]`
          ) as SVGPathElement | null;
          if (!path) return;
          const getNum = (name: string, fallback: number) => {
            const input = bulkheadList.querySelector(`input[name="${name}_${index}"]`) as
              | HTMLInputElement
              | null;
            const value = Number(input?.value ?? fallback);
            return Number.isFinite(value) && value > 0 ? value : fallback;
          };
          const outerDiameter = getNum("bulkhead_outer_diameter", 4);
          const thickness = getNum("bulkhead_thickness", 0.3);
          const viewW = 240;
          const viewH = 130;
          const pad = 14;
          const maxRectW = viewW - pad * 2;
          const maxRectH = viewH - pad * 2;
          const rectH = Math.min(maxRectH, Math.max(18, outerDiameter * 8));
          const rectW = Math.min(maxRectW, Math.max(8, thickness * 30));
          const x0 = (viewW - rectW) / 2;
          const y0 = (viewH - rectH) / 2;
          const x1 = x0 + rectW;
          const y1 = y0 + rectH;
          path.setAttribute(
            "d",
            `M ${x0} ${y1} L ${x1} ${y1} L ${x1} ${y0} L ${x0} ${y0} Z`
          );
        };
        const M_TO_FT = 3.28084;
        const M_TO_IN = 39.3701;
        const KG_TO_LB = 2.20462;
        const formatFixed = (value: number, digits = 2) => value.toFixed(digits);
        const extractMetric = (message: string, key: string) => {
          const match = message.match(new RegExp(`${key}=([0-9]*\\.?[0-9]+)`));
          return match ? Number(match[1]) : NaN;
        };
        const toImperialAutoBuildError = (detail: string) => {
          const raw = (detail || "").trim();
          const lower = raw.toLowerCase();
          if (!raw) return "UNKNOWN ERROR";
          if (lower.includes("exceeds feasible length budget")) {
            const upperLengthM = extractMetric(raw, "upper_length_m");
            const minRequiredM = extractMetric(raw, "min_required_length_m");
            const stages = extractMetric(raw, "stage_count");
            const stageText = Number.isFinite(stages) ? ` for ${Math.floor(stages)} stage(s)` : "";
            const upperIn = Number.isFinite(upperLengthM)
              ? `${formatFixed(upperLengthM * M_TO_IN, 2)} in`
              : "N/A";
            const minIn = Number.isFinite(minRequiredM)
              ? `${formatFixed(minRequiredM * M_TO_IN, 2)} in`
              : "N/A";
            return `Requested stage count${stageText} exceeds length budget. Max length: ${upperIn}; minimum required: ${minIn}. Increase max length or reduce stage count.`;
          }

          return raw
            .replace(/upper_length_m=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `upper_length_in=${Number.isFinite(n) ? formatFixed(n * M_TO_IN, 2) : v}`;
            })
            .replace(/min_required_length_m=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `min_required_length_in=${Number.isFinite(n) ? formatFixed(n * M_TO_IN, 2) : v}`;
            })
            .replace(/target_apogee_m=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `target_apogee_ft=${Number.isFinite(n) ? formatFixed(n * M_TO_FT, 0) : v}`;
            })
            .replace(/predicted_apogee_m=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `predicted_apogee_ft=${Number.isFinite(n) ? formatFixed(n * M_TO_FT, 0) : v}`;
            })
            .replace(/apogee_error_m=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `apogee_error_ft=${Number.isFinite(n) ? formatFixed(n * M_TO_FT, 0) : v}`;
            })
            .replace(/upper_mass_kg=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `upper_mass_lb=${Number.isFinite(n) ? formatFixed(n * KG_TO_LB, 2) : v}`;
            })
            .replace(/total_mass_kg=([0-9]*\.?[0-9]+)/g, (_, v) => {
              const n = Number(v);
              return `total_mass_lb=${Number.isFinite(n) ? formatFixed(n * KG_TO_LB, 2) : v}`;
            });
        };
        const renderAutoBuildResults = (result: unknown) => {
          if (!autoResultsEl) return;
          const payload = result as {
            assembly?: {
              metadata?: Record<string, unknown>;
              stages?: unknown[];
              body_tubes?: unknown[];
              fin_sets?: unknown[];
            };
          };
          const metadata = payload?.assembly?.metadata || {};
          const backendVariant = String(metadata.backend_variant ?? "unknown");
          const predictedApogeeM = Number(metadata.predicted_apogee_m ?? 0);
          const winnerScore = Number(metadata.winner_score ?? 0);
          const totalMassKg = Number(metadata.total_mass_kg ?? 0);
          const stabilityCal = Number(metadata.stability_margin_cal ?? 0);
          const ranked = Array.isArray(metadata.ranked_candidates)
            ? (metadata.ranked_candidates as Array<Record<string, unknown>>)
            : [];
          const targetInput = moduleR.querySelector('input[name="target_apogee_m"]') as
            | HTMLInputElement
            | null;
          const targetApogeeFt = Number(targetInput?.value || 0);
          const targetApogeeM =
            Number.isFinite(targetApogeeFt) && targetApogeeFt > 0 ? targetApogeeFt * 0.3048 : 0;
          const apogeeFt = predictedApogeeM > 0 ? predictedApogeeM * M_TO_FT : 0;
          const massLb = totalMassKg > 0 ? totalMassKg * KG_TO_LB : 0;
          const stages = payload.assembly?.stages?.length || 0;
          const tubes = payload.assembly?.body_tubes?.length || 0;
          const fins = payload.assembly?.fin_sets?.length || 0;

          const rows = ranked
            .slice(0, 5)
            .map((item, idx) => {
              const score = Number(item.score ?? 0).toFixed(3);
              const apogee = Number(item.predicted_apogee_m ?? 0);
              const apogeeFeet = (apogee * M_TO_FT).toFixed(0);
              const errM = Number(
                item.apogee_error_m ??
                  (targetApogeeM > 0 ? Math.abs(apogee - targetApogeeM) : 0)
              );
              const errFt = (errM * M_TO_FT).toFixed(0);
              const mass = Number(item.total_mass_kg ?? 0);
              const massPounds = mass * KG_TO_LB;
              const margin = Number(item.stability_margin_cal ?? 0);
              return `<tr>
                <td>${idx + 1}</td>
                <td>${apogeeFeet} ft</td>
                <td>${errFt} ft</td>
                <td>${massPounds.toFixed(2)} lb</td>
                <td>${margin.toFixed(2)} cal</td>
                <td>${score}</td>
              </tr>`;
            })
            .join("");

          autoResultsEl.innerHTML = `
            <div class="module-r-auto-result-card">
              <div class="module-r-auto-result-title">WINNER SUMMARY</div>
              <div class="module-r-auto-kpis">
                <span>Predicted Apogee: ${apogeeFt.toFixed(0)} ft</span>
                <span>Total Mass: ${massLb.toFixed(2)} lb</span>
                <span>Stability: ${stabilityCal.toFixed(2)} cal</span>
                <span>Winner Score: ${winnerScore.toFixed(3)}</span>
                <span>Backend Variant: ${backendVariant}</span>
                <span>Stages: ${stages}</span>
                <span>Body Tubes: ${tubes}</span>
                <span>Fin Sets: ${fins}</span>
              </div>
              <div class="module-r-auto-result-title">TOP CANDIDATES</div>
              <table class="module-r-auto-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Apogee</th>
                    <th>Error</th>
                    <th>Mass</th>
                    <th>Stability</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows || `<tr><td colspan="6">No ranked candidates returned.</td></tr>`}
                </tbody>
              </table>
            </div>
          `;
        };

        const getModuleRCompletionState = () => {
          const safeParse = <T,>(raw: string | null, fallback: T): T => {
            if (!raw) return fallback;
            try {
              return JSON.parse(raw) as T;
            } catch {
              return fallback;
            }
          };
          const stageCount = Number(window.localStorage.getItem("arx_module_r_stage_count") || "0");
          const motorOwned = window.localStorage.getItem("arx_module_r_motor_owned") === "true";
          const motorMounts = safeParse<
            Array<{ length_in?: number; inner_tube_diameter_in?: number; inner_tube_thickness_in?: number }>
          >(window.localStorage.getItem("arx_module_r_motor_mounts"), []);
          const motorDone =
            motorOwned &&
            Number.isFinite(stageCount) &&
            stageCount >= 1 &&
            motorMounts.length === stageCount &&
            motorMounts.every(
              (item) =>
                Number.isFinite(Number(item.length_in)) &&
                Number(item.length_in) > 0 &&
                Number.isFinite(Number(item.inner_tube_diameter_in)) &&
                Number(item.inner_tube_diameter_in) > 0 &&
                Number.isFinite(Number(item.inner_tube_thickness_in)) &&
                Number(item.inner_tube_thickness_in) > 0
            );

          const additionalCount = Number(
            window.localStorage.getItem("arx_module_r_additional_count") || "0"
          );
          const additionalOwned =
            window.localStorage.getItem("arx_module_r_additional_owned") === "true";
          const additionalTubes = safeParse<
            Array<{
              tube?: number;
              components?: Array<{
                name?: string;
                type?: string;
                mass_lb?: number;
                drag_coefficient?: number;
                is_override_active?: boolean;
                manual_override_mass_lb?: number;
              }>;
            }>
          >(window.localStorage.getItem("arx_module_r_additional_tubes"), []);
          const additionalDone =
            additionalOwned &&
            Number.isFinite(additionalCount) &&
            additionalCount >= 0 &&
            (additionalCount === 0 ||
              (additionalTubes.length === additionalCount &&
                additionalTubes.every((tube) => {
                  const components = Array.isArray(tube.components) ? tube.components : [];
                  return (
                    components.length > 0 &&
                    components.every((component) => {
                      const nameValid = String(component.name || "").trim().length > 0;
                      const type = String(component.type || "");
                      const typeValid = type.length > 0;
                      const mass = Number(component.mass_lb);
                      const massValid = Number.isFinite(mass) && mass >= 0;
                      const overrideActive = Boolean(component.is_override_active);
                      const overrideMass = Number(component.manual_override_mass_lb);
                      const overrideValid =
                        !overrideActive || (Number.isFinite(overrideMass) && overrideMass >= 0);
                      const drag = Number(component.drag_coefficient);
                      const dragValid =
                        type !== "parachute" || (Number.isFinite(drag) && drag > 0);
                      return nameValid && typeValid && massValid && overrideValid && dragValid;
                    })
                  );
                })));

          const bulkheadCount = Number(window.localStorage.getItem("arx_module_r_bulkhead_count") || "0");
          const bulkheadsOwned =
            window.localStorage.getItem("arx_module_r_bulkheads_owned") === "true";
          const bulkheads = safeParse<
            Array<{
              outer_diameter_in?: number;
              thickness_in?: number;
              position_in?: number;
              material?: string;
            }>
          >(window.localStorage.getItem("arx_module_r_bulkheads"), []);
          const bulkheadsDone =
            bulkheadsOwned &&
            Number.isFinite(bulkheadCount) &&
            bulkheadCount >= 1 &&
            bulkheads.length === bulkheadCount &&
            bulkheads.every(
              (item) =>
                Number.isFinite(Number(item.outer_diameter_in)) &&
                Number(item.outer_diameter_in) > 0 &&
                Number.isFinite(Number(item.thickness_in)) &&
                Number(item.thickness_in) > 0 &&
                Number.isFinite(Number(item.position_in)) &&
                Number(item.position_in) >= 0 &&
                String(item.material || "").length > 0
            );

          const nose = safeParse<{ length_in?: number; profile?: string; material?: string }>(
            window.localStorage.getItem("arx_module_r_nose_cone"),
            {}
          );
          const noseDone =
            Number.isFinite(Number(nose.length_in)) &&
            Number(nose.length_in) > 0 &&
            String(nose.profile || "").length > 0 &&
            String(nose.material || "").length > 0;

          const finSetCount = Number(window.localStorage.getItem("arx_module_r_fin_set_count") || "0");
          const fins = safeParse<Array<Record<string, unknown>>>(
            window.localStorage.getItem("arx_module_r_fins"),
            []
          );
          const finsDone =
            Number.isFinite(finSetCount) &&
            finSetCount >= 1 &&
            fins.length === finSetCount &&
            fins.every((f) => {
              const count = Number(f.count);
              const root = Number(f.root);
              const span = Number(f.span);
              return (
                Number.isFinite(count) &&
                count >= 2 &&
                Number.isFinite(root) &&
                root > 0 &&
                Number.isFinite(span) &&
                span > 0
              );
            });

          const bodyDone = motorDone && additionalDone && bulkheadsDone;
          const allDone = bodyDone && noseDone && finsDone;
          return { motorDone, additionalDone, bulkheadsDone, bodyDone, noseDone, finsDone, allDone };
        };
        const updateCardStates = () => {
          const {
            motorDone,
            additionalDone,
            bulkheadsDone,
            bodyDone,
            noseDone,
            finsDone,
            allDone,
          } = getModuleRCompletionState();
          // Keep done flags synchronized with derived hierarchy state.
          window.localStorage.setItem("arx_module_r_body_motor_done", motorDone ? "true" : "false");
          window.localStorage.setItem(
            "arx_module_r_body_additional_done",
            additionalDone ? "true" : "false"
          );
          window.localStorage.setItem(
            "arx_module_r_body_bulkheads_done",
            bulkheadsDone ? "true" : "false"
          );
          window.localStorage.setItem("arx_module_r_body_done", bodyDone ? "true" : "false");
          window.localStorage.setItem("arx_module_r_nose_done", noseDone ? "true" : "false");
          window.localStorage.setItem("arx_module_r_fins_done", finsDone ? "true" : "false");

          cardBody?.classList.toggle("module-r-complete", bodyDone);
          cardNose?.classList.toggle("module-r-complete", noseDone);
          cardFins?.classList.toggle("module-r-complete", finsDone);
          openBulkheads?.classList.toggle("module-r-complete", bulkheadsDone);
          openMotorMounts?.classList.toggle("module-r-complete", motorDone);
          openAdditionalTubes?.classList.toggle("module-r-complete", additionalDone);

          if (cardPositioning) {
            cardPositioning.classList.toggle("module-r-locked", !allDone);
            cardPositioning.classList.toggle("module-r-next", allDone);
          }
        };
        const collectMotorMountsFromForm = () => {
          if (!stageList) return [];
          const lengthInputs = Array.from(
            stageList.querySelectorAll('input[name^="stage_length_"]')
          ) as HTMLInputElement[];
          const innerDiameterInputs = Array.from(
            stageList.querySelectorAll('input[name^="inner_tube_diameter_"]')
          ) as HTMLInputElement[];
          const innerThicknessInputs = Array.from(
            stageList.querySelectorAll('input[name^="inner_tube_thickness_"]')
          ) as HTMLInputElement[];
          return lengthInputs.map((input, idx) => ({
            length_in: Number(input.value || 0),
            bulkhead_height_in: Math.max(
              Number((innerThicknessInputs[idx] as HTMLInputElement | undefined)?.value || 0.1),
              0.05
            ),
            bulkhead_material: "Cardboard",
            inner_tube_diameter_in: Number(
              (innerDiameterInputs[idx] as HTMLInputElement | undefined)?.value || 0
            ),
            inner_tube_thickness_in: Number(
              (innerThicknessInputs[idx] as HTMLInputElement | undefined)?.value || 0
            ),
          }));
        };
        const persistMotorMountDraft = () => {
          const count = Number(stageCountInput?.value || "0");
          if (!Number.isFinite(count) || count < 1) {
            window.localStorage.removeItem("arx_module_r_motor_owned");
            window.localStorage.setItem("arx_module_r_body_motor_done", "false");
            updateCardStates();
            return;
          }
          window.localStorage.setItem("arx_module_r_motor_owned", "true");
          window.localStorage.setItem("arx_module_r_stage_count", String(count));
          const stages = collectMotorMountsFromForm();
          window.localStorage.setItem("arx_module_r_motor_mounts", JSON.stringify(stages));
          const done =
            stages.length === count &&
            stages.every(
              (item) =>
                Number.isFinite(item.length_in) &&
                item.length_in > 0 &&
                Number.isFinite(item.inner_tube_diameter_in) &&
                item.inner_tube_diameter_in > 0 &&
                Number.isFinite(item.inner_tube_thickness_in) &&
                item.inner_tube_thickness_in > 0
            );
          window.localStorage.setItem("arx_module_r_body_motor_done", done ? "true" : "false");
          updateCardStates();
        };
        const collectAdditionalTubesFromForm = (tubeCount: number) => {
          if (!additionalList || tubeCount < 0) return [];
          return Array.from({ length: tubeCount }, (_, idx) => {
            const tubeIndex = idx + 1;
            const container = additionalList.querySelector(
              `.module-r-additional-components[data-tube="${tubeIndex}"]`
            ) as HTMLElement | null;
            const tubeComponents = Array.from(
              container?.querySelectorAll(".module-r-additional-component") || []
            ).map((component) => {
              const nameInput = component.querySelector('input[data-field="name"]') as
                | HTMLInputElement
                | null;
              const typeSelect = component.querySelector('select[data-field="type"]') as
                | HTMLSelectElement
                | null;
              const massInput = component.querySelector('input[data-field="mass"]') as
                | HTMLInputElement
                | null;
              const overrideToggle = component.querySelector('input[data-field="override_active"]') as
                | HTMLInputElement
                | null;
              const overrideMassInput = component.querySelector('input[data-field="override_mass"]') as
                | HTMLInputElement
                | null;
              const dragInput = component.querySelector('input[data-field="drag"]') as
                | HTMLInputElement
                | null;
              const parachuteMaterialInput = component.querySelector(
                'input[data-field="parachute_material"]'
              ) as HTMLInputElement | null;
              const parachuteDisplayInput = component.querySelector(
                'input[data-field="parachute_display"]'
              ) as HTMLInputElement | null;
              return {
                name: String(nameInput?.value || "").trim(),
                type: String(typeSelect?.value || ""),
                mass_lb: Number(massInput?.value || 0),
                drag_coefficient: Number(dragInput?.value || 0),
                parachute_material: String(parachuteMaterialInput?.value || "Nylon"),
                parachute_library_id: String(component.getAttribute("data-parachute-id") || ""),
                parachute_model: String(parachuteDisplayInput?.value || ""),
                is_override_active: Boolean(overrideToggle?.checked),
                manual_override_mass_lb: Number(overrideMassInput?.value || 0),
              };
            });
            return { tube: tubeIndex, components: tubeComponents };
          });
        };
        const isAdditionalComponentComplete = (
          component: (ReturnType<typeof collectAdditionalTubesFromForm>[number]["components"])[number]
        ) => {
          const nameValid = component.name.length > 0;
          const typeValid = component.type.length > 0;
          const massValid = Number.isFinite(component.mass_lb) && component.mass_lb >= 0;
          const overrideValid =
            !component.is_override_active ||
            (Number.isFinite(component.manual_override_mass_lb) &&
              component.manual_override_mass_lb >= 0);
          const dragValid =
            component.type !== "parachute" ||
            (Number.isFinite(component.drag_coefficient) && component.drag_coefficient > 0);
          return nameValid && typeValid && massValid && overrideValid && dragValid;
        };
        const persistAdditionalDraft = () => {
          const count = Number(additionalCountInput?.value || "0");
          if (!Number.isFinite(count) || count < 0) {
            window.localStorage.removeItem("arx_module_r_additional_owned");
            window.localStorage.setItem("arx_module_r_body_additional_done", "false");
            updateCardStates();
            return;
          }
          window.localStorage.setItem("arx_module_r_additional_owned", "true");
          window.localStorage.setItem("arx_module_r_additional_count", String(count));
          const tubes = collectAdditionalTubesFromForm(count);
          window.localStorage.setItem("arx_module_r_additional_tubes", JSON.stringify(tubes));
          const done =
            count === 0 ||
            (tubes.length === count &&
              tubes.every(
                (tube) =>
                  Array.isArray(tube.components) &&
                  tube.components.length > 0 &&
                  tube.components.every(isAdditionalComponentComplete)
              ));
          window.localStorage.setItem("arx_module_r_body_additional_done", done ? "true" : "false");
          updateCardStates();
        };
        const collectBulkheadsFromForm = (count: number) => {
          if (!bulkheadList || count < 1) return [];
          return Array.from({ length: count }, (_, idx) => {
            const i = idx + 1;
            const getNumber = (name: string, fallback = 0) => {
              const input = bulkheadList.querySelector(`input[name="${name}_${i}"]`) as
                | HTMLInputElement
                | null;
              const value = Number(input?.value ?? fallback);
              return Number.isFinite(value) ? value : fallback;
            };
            const getSelect = (name: string) =>
              bulkheadList.querySelector(`select[name="${name}_${i}"]`) as
                | HTMLSelectElement
                | null;
            return {
              outer_diameter_in: getNumber("bulkhead_outer_diameter", 0),
              thickness_in: getNumber("bulkhead_thickness", 0),
              position_in: getNumber("bulkhead_position", 0),
              material: getSelect("bulkhead_material_detail")?.value || "Cardboard",
            };
          });
        };
        const persistBulkheadDraft = () => {
          const count = Number(bulkheadCountInput?.value || "0");
          if (!Number.isFinite(count) || count < 1) {
            window.localStorage.removeItem("arx_module_r_bulkheads_owned");
            window.localStorage.setItem("arx_module_r_body_bulkheads_done", "false");
            updateCardStates();
            return;
          }
          window.localStorage.setItem("arx_module_r_bulkheads_owned", "true");
          window.localStorage.setItem("arx_module_r_bulkhead_count", String(count));
          const bulkheads = collectBulkheadsFromForm(count);
          window.localStorage.setItem("arx_module_r_bulkheads", JSON.stringify(bulkheads));
          const done =
            bulkheads.length === count &&
            bulkheads.every(
              (item) =>
                Number.isFinite(item.outer_diameter_in) &&
                item.outer_diameter_in > 0 &&
                Number.isFinite(item.thickness_in) &&
                item.thickness_in > 0 &&
                Number.isFinite(item.position_in) &&
                item.position_in >= 0 &&
                Boolean(item.material)
            );
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", done ? "true" : "false");
          updateCardStates();
        };
        const syncAdditionalComponentUI = (componentNode: HTMLElement) => {
          const typeSelect = componentNode.querySelector('select[data-field="type"]') as
            | HTMLSelectElement
            | null;
          const isParachute = typeSelect?.value === "parachute";
          const picker = componentNode.querySelector('[data-parachute-picker]') as HTMLElement | null;
          const dragField = componentNode.querySelector('[data-parachute-drag]') as HTMLElement | null;
          const overrideToggle = componentNode.querySelector('input[data-field="override_active"]') as
            | HTMLInputElement
            | null;
          const overrideField = componentNode.querySelector('[data-override-mass]') as HTMLElement | null;
          if (picker) picker.style.display = isParachute ? "grid" : "none";
          if (dragField) dragField.style.display = isParachute ? "grid" : "none";
          if (overrideField) overrideField.style.display = overrideToggle?.checked ? "grid" : "none";
        };

        showPage("init");
        enhanceModuleRSelects();
        if (ricInput) {
          ricInput.style.display = "none";
        }
        const storedAutoPrefsRaw = window.localStorage.getItem("arx_module_r_auto_prefs");
        if (storedAutoPrefsRaw) {
          try {
            const stored = JSON.parse(storedAutoPrefsRaw) as Record<string, unknown>;
            const lengthInput = moduleR.querySelector('input[name="upper_length_m"]') as
              | HTMLInputElement
              | null;
            const massInput = moduleR.querySelector('input[name="upper_mass_kg"]') as
              | HTMLInputElement
              | null;
            const apogeeInput = moduleR.querySelector('input[name="target_apogee_m"]') as
              | HTMLInputElement
              | null;
            const topNInput = moduleR.querySelector('input[name="top_n"]') as
              | HTMLInputElement
              | null;
            const seedInput = moduleR.querySelector('input[name="random_seed"]') as
              | HTMLInputElement
              | null;
            const includeBallast = moduleR.querySelector('input[name="include_ballast"]') as
              | HTMLInputElement
              | null;
            const includeTelemetry = moduleR.querySelector('input[name="include_telemetry"]') as
              | HTMLInputElement
              | null;
            const includeParachute = moduleR.querySelector('input[name="include_parachute"]') as
              | HTMLInputElement
              | null;
            if (lengthInput && typeof stored.upper_length_in === "number") {
              lengthInput.value = String(stored.upper_length_in);
            }
            if (massInput && typeof stored.upper_mass_lb === "number") {
              massInput.value = String(stored.upper_mass_lb);
            }
            if (apogeeInput && typeof stored.target_apogee_ft === "number") {
              apogeeInput.value = String(stored.target_apogee_ft);
            }
            if (topNInput && typeof stored.top_n === "number") {
              topNInput.value = String(stored.top_n);
            }
            if (seedInput && typeof stored.random_seed === "number") {
              seedInput.value = String(stored.random_seed);
            }
            if (includeBallast && typeof stored.include_ballast === "boolean") {
              includeBallast.checked = stored.include_ballast;
            }
            if (includeTelemetry && typeof stored.include_telemetry === "boolean") {
              includeTelemetry.checked = stored.include_telemetry;
            }
            if (includeParachute && typeof stored.include_parachute === "boolean") {
              includeParachute.checked = stored.include_parachute;
            }
          } catch (error) {
            console.warn("Failed to parse auto-build prefs", error);
          }
        }
        updateCardStates();

        pickRicBtn?.addEventListener("click", () => {
          ricInput?.click();
        });

        ricInput?.addEventListener("change", () => {
          if (!ricName) return;
          const files = ricInput.files ? Array.from(ricInput.files) : [];
          if (!files.length) {
            ricName.textContent = "No file chosen";
          } else if (files.length === 1) {
            ricName.textContent = files[0].name;
          } else {
            ricName.textContent = `${files.length} files selected`;
          }
        });

        lockBtn?.addEventListener("click", () => {
          if (!widthInput) return;
          const value = Number(widthInput.value);
          if (!Number.isFinite(value) || value <= 0) {
            setStatus("ENTER A VALID DIAMETER.");
            return;
          }
          widthInput.disabled = true;
          window.localStorage.setItem("arx_module_r_width", String(value));
          setStatus("WIDTH LOCKED.");
          showPage("entry");
        });

        resetBtn?.addEventListener("click", () => {
          if (widthInput) {
            widthInput.value = "";
            widthInput.disabled = false;
          }
          window.localStorage.removeItem("arx_module_r_width");
          setStatus("WIDTH RESET.");
        });

        manualBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_mode", "MANUAL");
          window.localStorage.removeItem("arx_module_r_latest_auto_assembly");
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          showPage("manual");
          setStatus("MANUAL MODE SELECTED.");
        });

        const stageModal = moduleR.querySelector(".module-r-stage-modal") as HTMLElement | null;
        const stageInput = moduleR.querySelector('input[name="stage_count"]') as
          | HTMLInputElement
          | null;
        const stageConfirm = moduleR.querySelector('[data-action="stage-confirm"]') as
          | HTMLButtonElement
          | null;
        const stageCancel = moduleR.querySelector('[data-action="stage-cancel"]') as
          | HTMLButtonElement
          | null;

        const openStageModal = () => {
          if (!stageModal || !stageInput) return;
          stageModal.classList.add("active");
          stageInput.value = "1";
          stageInput.focus();
        };

        const closeStageModal = () => {
          stageModal?.classList.remove("active");
        };

        autoBtn?.addEventListener("click", () => {
          openStageModal();
        });

        stageCancel?.addEventListener("click", () => {
          closeStageModal();
        });

        stageConfirm?.addEventListener("click", () => {
          const stages = Number(stageInput?.value);
          if (!Number.isFinite(stages) || stages < 1 || stages > 5) {
            setStatus("ENTER A STAGE COUNT BETWEEN 1 AND 5.");
            return;
          }
          window.localStorage.setItem("arx_module_r_stage_count", String(stages));
          window.localStorage.setItem("arx_module_r_mode", "AUTO");
          window.localStorage.removeItem("arx_module_r_latest_auto_assembly");
          closeStageModal();
          showPage("auto");
          setStatus("AUTO MODE SELECTED.");
        });

        backInitBtn?.addEventListener("click", () => {
          showPage("init");
          setStatus("");
        });

        backEntryBtn.forEach((button) => {
          button.addEventListener("click", () => {
            showPage("entry");
            setStatus("");
          });
        });

        cardBody?.addEventListener("click", () => {
          showPage("body");
        });
        cardNose?.addEventListener("click", () => {
          showPage("nose");
        });
        cardFins?.addEventListener("click", () => {
          showPage("fins");
        });
        cardPositioning?.addEventListener("click", () => {
          const { allDone } = getModuleRCompletionState();
          if (!allDone) {
            setStatus("COMPLETE BODY TUBES, NOSE CONES, AND FINS FIRST.");
            return;
          }
          showPage("positioning");
        });

        backManualBtns.forEach((button) => {
          button.addEventListener("click", () => {
            showPage("manual");
            setStatus("");
          });
        });

        const buildPositioningList = () => {
          if (!storageList || !workspaceDrop) return;
          const items: string[] = [];
          const stageCount = Number(
            window.localStorage.getItem("arx_module_r_stage_count") || "1"
          );
          const additionalCount = Number(
            window.localStorage.getItem("arx_module_r_additional_count") || "0"
          );
          for (let i = 1; i <= stageCount; i += 1) {
            items.push(`Stage ${i} Motor Mount`);
          }
          for (let i = 1; i <= additionalCount; i += 1) {
            items.push(`Additional Tube ${i}`);
          }
          items.push("Nose Cone");
          const finCount = Number(
            window.localStorage.getItem("arx_module_r_fin_set_count") || "0"
          );
          for (let i = 1; i <= finCount; i += 1) {
            items.push(`Fin Set ${i}`);
          }

          storageList.innerHTML = "";
          workspaceDrop.innerHTML = '<div class="module-r-workspace-hint">DROP COMPONENTS HERE</div>';

          items.forEach((label) => {
            const item = document.createElement("div");
            item.className = "module-r-item";
            item.innerHTML = `
              <div class="module-r-item-shape"></div>
              <div class="module-r-item-label">${label}</div>
            `;
            item.draggable = true;
            item.addEventListener("dragstart", (event) => {
              event.dataTransfer?.setData("text/plain", label);
            });
            storageList.appendChild(item);
          });
        };

        const setupDropZone = (zone: HTMLElement) => {
          zone.addEventListener("dragover", (event) => {
            event.preventDefault();
            zone.classList.add("module-r-drop-active");
          });
          zone.addEventListener("dragleave", () => {
            zone.classList.remove("module-r-drop-active");
          });
          zone.addEventListener("drop", (event) => {
            event.preventDefault();
            zone.classList.remove("module-r-drop-active");
            const label = event.dataTransfer?.getData("text/plain");
            if (!label) return;
            const item = document.createElement("div");
            item.className = "module-r-item";
            item.innerHTML = `
              <div class="module-r-item-shape"></div>
              <div class="module-r-item-label">${label}</div>
            `;
            item.draggable = true;
            item.addEventListener("dragstart", (evt) => {
              evt.dataTransfer?.setData("text/plain", label);
            });
            zone.appendChild(item);
          });
        };

        if (workspaceDrop) {
          setupDropZone(workspaceDrop);
        }
        if (storageList) {
          setupDropZone(storageList);
        }

        savePositioningBtn?.addEventListener("click", () => {
          if (!workspaceDrop) return;
          const items = Array.from(workspaceDrop.querySelectorAll(".module-r-item")).map(
            (node) => (node as HTMLElement).textContent || ""
          );
          window.localStorage.setItem("arx_module_r_stack", JSON.stringify(items));
          setStatus("POSITIONING SAVED.");
          window.alert("Positioning saved.");
        });

        openMotorMounts?.addEventListener("click", () => {
          showPage("motor-mounts");
          setStatus("");
        });
        openAdditionalTubes?.addEventListener("click", () => {
          showPage("additional-tubes");
          setStatus("");
        });
        openBulkheads?.addEventListener("click", () => {
          showPage("bulkheads");
          setStatus("");
        });
        backBodyBtns.forEach((btn) => {
          btn.addEventListener("click", () => {
            showPage("body");
            setStatus("");
          });
        });
        backMotorMounts?.addEventListener("click", () => {
          showPage("motor-mounts");
          setStatus("");
        });
        backAdditional?.addEventListener("click", () => {
          showPage("additional-tubes");
          setStatus("");
        });
        backBulkheads?.addEventListener("click", () => {
          showPage("bulkheads");
          setStatus("");
        });

        motorMountsNext?.addEventListener("click", () => {
          if (!stageCountInput || !stageList) return;
          const count = Number(stageCountInput.value);
          if (!Number.isFinite(count) || count < 1 || count > 5) {
            setStatus("ENTER STAGE COUNT BETWEEN 1 AND 5.");
            return;
          }
          window.localStorage.setItem("arx_module_r_stage_count", String(count));
          const widthValue = Number(window.localStorage.getItem("arx_module_r_width") || "0");
          // Motor-mount tube should be much smaller than body diameter by default.
          const suggestedDiameter = widthValue > 0 ? Math.max(widthValue * 0.34, 0.75) : 0;
          const suggestedThickness = widthValue > 0 ? Math.max(widthValue * 0.018, 0.06) : 0;
          const suggestedDiameterText =
            widthValue > 0 ? `${suggestedDiameter.toFixed(2)} IN` : "N/A";
          const suggestedThicknessText =
            widthValue > 0 ? `${suggestedThickness.toFixed(2)} IN` : "N/A";
          const savedStages = JSON.parse(
            window.localStorage.getItem("arx_module_r_motor_mounts") || "[]"
          ) as Array<{
            length_in?: number;
            inner_tube_diameter_in?: number;
            inner_tube_thickness_in?: number;
          }>;
          const stageRows: string[] = [];
          for (let i = 1; i <= count; i += 1) {
            const saved = savedStages[i - 1] || {};
            stageRows.push(`
              <div class="module-r-fin-row module-r-stage-row" data-stage-row="${i}">
                <div class="module-r-fin-fields">
                  <div class="module-r-finset-title">STAGE ${i}</div>
                  <div class="launch-modal-grid">
                    <div class="arx-field">
                      <input type="number" name="stage_length_${i}" placeholder=" " min="0" step="any" value="${Number(saved.length_in || 0) > 0 ? Number(saved.length_in) : ""}" />
                      <label>STAGE ${i} LENGTH (IN)</label>
                    </div>
                    <div class="arx-field">
                      <input type="number" name="inner_tube_diameter_${i}" placeholder=" " min="0" step="any" value="${Number(saved.inner_tube_diameter_in || 0) > 0 ? Number(saved.inner_tube_diameter_in) : suggestedDiameter || ""}" />
                      <label>INNER TUBE ${i} DIAMETER (IN)</label>
                      <div class="field-hint">RECOMMENDED: ${suggestedDiameterText}</div>
                    </div>
                    <div class="arx-field">
                      <input type="number" name="inner_tube_thickness_${i}" placeholder=" " min="0" step="any" value="${Number(saved.inner_tube_thickness_in || 0) > 0 ? Number(saved.inner_tube_thickness_in) : suggestedThickness || ""}" />
                      <label>INNER TUBE ${i} THICKNESS (IN)</label>
                      <div class="field-hint">RECOMMENDED: ${suggestedThicknessText}</div>
                    </div>
                  </div>
                </div>
                <div class="module-r-fin-preview-grid">
                  <div class="module-r-fin-preview-title">M${i} GRID</div>
                  <svg class="module-r-fin-preview-svg" data-stage-preview="${i}" viewBox="0 0 240 130" preserveAspectRatio="xMidYMid meet">
                    <defs>
                      <pattern id="stage-grid-${i}" width="12" height="12" patternUnits="userSpaceOnUse">
                        <path d="M 12 0 L 0 0 0 12" fill="none" stroke="rgba(0,243,255,0.25)" stroke-width="1" />
                      </pattern>
                    </defs>
                    <rect x="0" y="0" width="240" height="130" fill="url(#stage-grid-${i})" />
                    <path data-stage-shape="${i}" d="M 16 102 L 214 102 L 214 26 L 16 26 Z" fill="rgba(0,243,255,0.15)" stroke="rgba(255,215,0,0.92)" stroke-width="2" fill-rule="evenodd" />
                  </svg>
                </div>
              </div>
            `);
          }
          stageList.innerHTML = stageRows.join("");
          for (let i = 1; i <= count; i += 1) {
            ["stage_length", "inner_tube_diameter", "inner_tube_thickness"].forEach((key) => {
              stageList
                .querySelector(`input[name="${key}_${i}"]`)
                ?.addEventListener("input", () => {
                  updateStagePreview(i);
                  persistMotorMountDraft();
                });
            });
            updateStagePreview(i);
          }
          persistMotorMountDraft();
          showPage("motor-mounts-detail");
        });

        motorMountsSave?.addEventListener("click", () => {
          if (!stageList) return;
          const lengthInputs = stageList.querySelectorAll('input[name^="stage_length_"]');
          const innerDiameterInputs = stageList.querySelectorAll(
            'input[name^="inner_tube_diameter_"]'
          );
          const innerThicknessInputs = stageList.querySelectorAll(
            'input[name^="inner_tube_thickness_"]'
          );
          const allLengthsValid = Array.from(lengthInputs).every((input) => {
            const value = Number((input as HTMLInputElement).value);
            return Number.isFinite(value) && value > 0;
          });
          const allInnerDiametersValid = Array.from(innerDiameterInputs).every((input) => {
            const value = Number((input as HTMLInputElement).value);
            return Number.isFinite(value) && value > 0;
          });
          const allInnerThicknessValid = Array.from(innerThicknessInputs).every((input) => {
            const value = Number((input as HTMLInputElement).value);
            return Number.isFinite(value) && value > 0;
          });
          if (
            !allLengthsValid ||
            !allInnerDiametersValid ||
            !allInnerThicknessValid
          ) {
            setStatus("COMPLETE ALL STAGE FIELDS BEFORE SAVING.");
            return;
          }
          const stages = Array.from(lengthInputs).map((input, idx) => ({
            length_in: Number((input as HTMLInputElement).value),
            bulkhead_height_in: Math.max(
              Number((innerThicknessInputs[idx] as HTMLInputElement).value || 0.1),
              0.05
            ),
            bulkhead_material: "Cardboard",
            inner_tube_diameter_in: Number((innerDiameterInputs[idx] as HTMLInputElement).value),
            inner_tube_thickness_in: Number((innerThicknessInputs[idx] as HTMLInputElement).value),
          }));
          window.localStorage.setItem("arx_module_r_motor_mounts", JSON.stringify(stages));
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          setStatus("MOTOR MOUNTS SAVED.");
          window.localStorage.setItem("arx_module_r_body_motor_done", "true");
          updateCardStates();
          window.alert("Motor Mounts saved.");
          showPage("body");
        });

        motorMountsClear?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_motor_owned");
          window.localStorage.setItem("arx_module_r_body_motor_done", "false");
          window.localStorage.removeItem("arx_module_r_stage_count");
          window.localStorage.removeItem("arx_module_r_motor_mounts");
          if (stageCountInput) stageCountInput.value = "";
          if (stageList) stageList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          showPage("motor-mounts");
          setStatus("MOTOR MOUNTS CLEARED.");
        });

        motorMountsClearIndex?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_motor_owned");
          window.localStorage.setItem("arx_module_r_body_motor_done", "false");
          window.localStorage.removeItem("arx_module_r_stage_count");
          window.localStorage.removeItem("arx_module_r_motor_mounts");
          if (stageCountInput) stageCountInput.value = "";
          if (stageList) stageList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("MOTOR MOUNTS CLEARED.");
        });

        additionalNext?.addEventListener("click", () => {
          if (!additionalCountInput || !additionalList) return;
          const count = Number(additionalCountInput.value);
          if (!Number.isFinite(count) || count < 0 || count > 10) {
            setStatus("ENTER 0-10 ADDITIONAL TUBES.");
            return;
          }
          window.localStorage.setItem("arx_module_r_additional_count", String(count));
          additionalList.innerHTML = "";
          const savedAdditionalTubes = JSON.parse(
            window.localStorage.getItem("arx_module_r_additional_tubes") || "[]"
          ) as Array<{
            tube?: number;
            components?: Array<{
              name?: string;
              type?: string;
              mass_lb?: number;
              drag_coefficient?: number;
              parachute_material?: string;
              parachute_library_id?: string;
              parachute_model?: string;
              is_override_active?: boolean;
              manual_override_mass_lb?: number;
            }>;
          }>;
          const escAttr = (value: string) => value.replace(/"/g, "&quot;");
          const componentTemplate = (
            tubeIndex: number,
            componentIndex: number,
            initial?: {
              name?: string;
              type?: string;
              mass_lb?: number;
              drag_coefficient?: number;
              parachute_material?: string;
              parachute_library_id?: string;
              parachute_model?: string;
              is_override_active?: boolean;
              manual_override_mass_lb?: number;
            }
          ) => `
            <div class="module-r-additional-component" data-component-id="tube-${tubeIndex}-component-${componentIndex}"${
              initial?.parachute_library_id
                ? ` data-parachute-id="${escAttr(String(initial.parachute_library_id))}"`
                : ""
            }>
              <div class="launch-modal-grid">
                <div class="arx-field">
                  <input type="text" data-field="name" name="additional_name_${tubeIndex}_${componentIndex}" placeholder=" " value="${
                    initial?.name ? escAttr(String(initial.name)) : ""
                  }" />
                  <label>COMPONENT ${componentIndex} NAME</label>
                </div>
                <div class="arx-field">
                  <select data-field="type" name="additional_type_${tubeIndex}_${componentIndex}">
                    <option value="telemetry" ${
                      (initial?.type || "telemetry") === "telemetry" ? "selected" : ""
                    }>Telemetry Module</option>
                    <option value="mass" ${initial?.type === "mass" ? "selected" : ""}>Mass Component</option>
                    <option value="inner_tube" ${
                      initial?.type === "inner_tube" ? "selected" : ""
                    }>Inner Tube</option>
                    <option value="parachute" ${
                      initial?.type === "parachute" ? "selected" : ""
                    }>Parachute</option>
                  </select>
                </div>
                <div class="arx-field">
                  <input type="number" data-field="mass" name="additional_mass_${tubeIndex}_${componentIndex}" placeholder=" " min="0" step="any" value="${
                    Number(initial?.mass_lb || 0) > 0 ? Number(initial?.mass_lb) : ""
                  }" />
                  <label>MASS (LB)</label>
                </div>
                <div class="arx-field" data-parachute-picker style="display:none;">
                  <input type="text" data-field="parachute_display" name="additional_parachute_display_${tubeIndex}_${componentIndex}" placeholder=" " value="${
                    initial?.parachute_model ? escAttr(String(initial.parachute_model)) : ""
                  }" readonly />
                  <label>PARACHUTE MODEL</label>
                  <button type="button" class="arx-btn module-r-parachute-pick-btn" data-action="pick-parachute-model">Select from Library</button>
                </div>
                <div class="arx-field" data-parachute-drag style="display:none;">
                  <input type="number" data-field="drag" name="additional_drag_${tubeIndex}_${componentIndex}" placeholder=" " min="0" step="any" value="${
                    Number(initial?.drag_coefficient || 0) > 0 ? Number(initial?.drag_coefficient) : ""
                  }" readonly />
                  <label>DRAG COEFFICIENT</label>
                </div>
                <input type="hidden" data-field="parachute_material" name="additional_material_${tubeIndex}_${componentIndex}" value="${
                  initial?.parachute_material
                    ? escAttr(String(initial.parachute_material))
                    : "Nylon"
                }" />
                <div class="arx-field">
                  <label class="nav-link module-r-fin-checkbox">
                    <input type="checkbox" data-field="override_active" name="additional_override_active_${tubeIndex}_${componentIndex}" ${
                      initial?.is_override_active ? "checked" : ""
                    } />
                    Override Mass
                  </label>
                </div>
                <div class="arx-field" data-override-mass style="display:none;">
                  <input type="number" data-field="override_mass" name="additional_override_mass_${tubeIndex}_${componentIndex}" placeholder=" " min="0" step="any" value="${
                    Number(initial?.manual_override_mass_lb || 0) > 0
                      ? Number(initial?.manual_override_mass_lb)
                      : ""
                  }" />
                  <label>OVERRIDE MASS (LB)</label>
                </div>
              </div>
            </div>
          `;
          for (let i = 1; i <= count; i += 1) {
            const savedTube = savedAdditionalTubes.find((tube) => Number(tube.tube) === i);
            const savedComponents = Array.isArray(savedTube?.components)
              ? savedTube?.components || []
              : [];
            const componentMarkup = (savedComponents.length
              ? savedComponents.map((component, idx) => componentTemplate(i, idx + 1, component))
              : [componentTemplate(i, 1)]
            ).join("");
            const nextIndex = Math.max(savedComponents.length + 1, 2);
            additionalList.innerHTML += `
              <div class="module-r-fin-row module-r-additional-tube" data-tube="${i}">
                <div class="module-r-fin-fields">
                  <div class="module-r-finset-title">TUBE ${i} COMPONENTS</div>
                  <div class="module-r-additional-components" data-tube="${i}" data-next-index="${nextIndex}">
                    ${componentMarkup}
                  </div>
                  <div class="arx-form-actions">
                    <button type="button" class="arx-btn" data-action="add-additional-component" data-tube="${i}">
                      Add Component
                    </button>
                  </div>
                </div>
                <div class="module-r-fin-preview-grid">
                  <div class="module-r-fin-preview-title">A${i} GRID</div>
                  <div class="module-r-additional-preview-shell">
                    <svg class="module-r-fin-preview-svg" data-additional-preview="${i}" viewBox="0 0 240 130" preserveAspectRatio="xMidYMid meet">
                      <defs>
                        <pattern id="additional-grid-${i}" width="12" height="12" patternUnits="userSpaceOnUse">
                          <path d="M 12 0 L 0 0 0 12" fill="none" stroke="rgba(0,243,255,0.25)" stroke-width="1" />
                        </pattern>
                      </defs>
                      <rect x="0" y="0" width="240" height="130" fill="url(#additional-grid-${i})" />
                      <path data-additional-shape="${i}" d="M 12 124 L 228 124 L 228 8 L 12 8 Z M 14 122 Q 120 108 226 122 L 226 124 L 14 124 Z" fill="rgba(0,243,255,0.18)" stroke="rgba(255,215,0,0.92)" stroke-width="2" fill-rule="evenodd" />
                      <g data-additional-telemetry="${i}" style="opacity:0;">
                        <circle class="module-r-telemetry-halo" cx="120" cy="66" r="26" />
                        <circle class="module-r-telemetry-halo" cx="120" cy="66" r="16" />
                        <circle class="module-r-telemetry-core" cx="120" cy="66" r="6" />
                        <path class="module-r-telemetry-stream" d="M 52 98 L 80 82 L 102 90 L 120 70 L 138 86 L 164 64 L 188 72" />
                      </g>
                      <g data-additional-parachute-icon="${i}" style="opacity:0;">
                        <path class="module-r-parachute-outline" d="M 58 72 C 72 44, 96 32, 120 32 C 144 32, 168 44, 182 72" />
                        <path class="module-r-parachute-outline" d="M 58 72 C 68 62, 78 60, 88 72 C 98 60, 108 58, 120 72 C 132 58, 142 60, 152 72 C 162 60, 172 62, 182 72" />
                        <line class="module-r-parachute-lines" x1="70" y1="72" x2="120" y2="108" />
                        <line class="module-r-parachute-lines" x1="88" y1="72" x2="120" y2="108" />
                        <line class="module-r-parachute-lines" x1="104" y1="72" x2="120" y2="108" />
                        <line class="module-r-parachute-lines" x1="136" y1="72" x2="120" y2="108" />
                        <line class="module-r-parachute-lines" x1="152" y1="72" x2="120" y2="108" />
                        <line class="module-r-parachute-lines" x1="170" y1="72" x2="120" y2="108" />
                        <path class="module-r-parachute-capsule" d="M 108 108 L 132 108 L 136 120 L 132 128 L 108 128 L 104 120 Z" />
                      </g>
                      <g data-additional-mass-icon="${i}" style="opacity:0;">
                        <rect class="module-r-mass-core" x="90" y="58" width="60" height="44" rx="4" />
                        <line class="module-r-mass-grid" x1="110" y1="58" x2="110" y2="102" />
                        <line class="module-r-mass-grid" x1="130" y1="58" x2="130" y2="102" />
                        <line class="module-r-mass-grid" x1="90" y1="74" x2="150" y2="74" />
                        <line class="module-r-mass-grid" x1="90" y1="88" x2="150" y2="88" />
                        <path class="module-r-mass-base" d="M 96 108 L 144 108 L 150 118 L 90 118 Z" />
                      </g>
                    </svg>
                    <video class="module-r-additional-media module-r-additional-media-telemetry" data-additional-telemetry-video="${i}" muted loop playsinline preload="auto"></video>
                    <img class="module-r-additional-media module-r-additional-media-image" data-additional-parachute-image="${i}" alt="" />
                    <img class="module-r-additional-media module-r-additional-media-image" data-additional-mass-image="${i}" alt="" />
                  </div>
                </div>
              </div>
            `;
            updateAdditionalPreview(i);
            const firstComponent = additionalList.querySelector(
              `.module-r-additional-components[data-tube="${i}"] .module-r-additional-component`
            ) as HTMLElement | null;
            if (firstComponent) syncAdditionalComponentUI(firstComponent);
          }
          persistAdditionalDraft();
          showPage("additional-detail");
        });

        additionalList?.addEventListener("click", (event) => {
          const target = event.target as HTMLElement | null;
          if (!target) return;
          const parachutePickBtn = target.closest(
            '[data-action="pick-parachute-model"]'
          ) as HTMLButtonElement | null;
          if (parachutePickBtn) {
            const componentNode = parachutePickBtn.closest(
              ".module-r-additional-component"
            ) as HTMLElement | null;
            if (!componentNode) return;
            openParachuteModal(componentNode);
            return;
          }
          const addBtn = target.closest(
            '[data-action="add-additional-component"]'
          ) as HTMLButtonElement | null;
          if (!addBtn) return;
          const tubeIndex = Number(addBtn.getAttribute("data-tube"));
          if (!Number.isFinite(tubeIndex)) return;
          const container = additionalList.querySelector(
            `.module-r-additional-components[data-tube="${tubeIndex}"]`
          ) as HTMLElement | null;
          if (!container) return;
          const nextIndex = Number(container.getAttribute("data-next-index") || "1");
          if (!Number.isFinite(nextIndex)) return;
          container.insertAdjacentHTML(
            "beforeend",
            `
            <div class="module-r-additional-component" data-component-id="tube-${tubeIndex}-component-${nextIndex}">
              <div class="launch-modal-grid">
                <div class="arx-field">
                  <input type="text" data-field="name" name="additional_name_${tubeIndex}_${nextIndex}" placeholder=" " />
                  <label>COMPONENT ${nextIndex} NAME</label>
                </div>
                <div class="arx-field">
                  <select data-field="type" name="additional_type_${tubeIndex}_${nextIndex}">
                    <option value="telemetry">Telemetry Module</option>
                    <option value="mass">Mass Component</option>
                    <option value="inner_tube">Inner Tube</option>
                    <option value="parachute">Parachute</option>
                  </select>
                </div>
                <div class="arx-field">
                  <input type="number" data-field="mass" name="additional_mass_${tubeIndex}_${nextIndex}" placeholder=" " min="0" step="any" />
                  <label>MASS (LB)</label>
                </div>
                <div class="arx-field" data-parachute-picker style="display:none;">
                  <input type="text" data-field="parachute_display" name="additional_parachute_display_${tubeIndex}_${nextIndex}" placeholder=" " readonly />
                  <label>PARACHUTE MODEL</label>
                  <button type="button" class="arx-btn module-r-parachute-pick-btn" data-action="pick-parachute-model">Select from Library</button>
                </div>
                <div class="arx-field" data-parachute-drag style="display:none;">
                  <input type="number" data-field="drag" name="additional_drag_${tubeIndex}_${nextIndex}" placeholder=" " min="0" step="any" readonly />
                  <label>DRAG COEFFICIENT</label>
                </div>
                <input type="hidden" data-field="parachute_material" name="additional_material_${tubeIndex}_${nextIndex}" value="Nylon" />
                <div class="arx-field">
                  <label class="nav-link module-r-fin-checkbox">
                    <input type="checkbox" data-field="override_active" name="additional_override_active_${tubeIndex}_${nextIndex}" />
                    Override Mass
                  </label>
                </div>
                <div class="arx-field" data-override-mass style="display:none;">
                  <input type="number" data-field="override_mass" name="additional_override_mass_${tubeIndex}_${nextIndex}" placeholder=" " min="0" step="any" />
                  <label>OVERRIDE MASS (LB)</label>
                </div>
              </div>
            </div>
          `
          );
          container.setAttribute("data-next-index", String(nextIndex + 1));
          const addedComponent = container.querySelector(
            `.module-r-additional-component[data-component-id="tube-${tubeIndex}-component-${nextIndex}"]`
          ) as HTMLElement | null;
          if (addedComponent) syncAdditionalComponentUI(addedComponent);
          updateAdditionalPreview(tubeIndex);
          persistAdditionalDraft();
          enhanceModuleRSelects();
        });
        moduleR.addEventListener("click", (event) => {
          const target = event.target as HTMLElement | null;
          if (!target) return;
          const closeBtn = target.closest('[data-action="close-parachute-modal"]') as
            | HTMLButtonElement
            | null;
          if (closeBtn) {
            closeParachuteModal();
            return;
          }
          const applyBtn = target.closest('[data-action="apply-parachute-modal"]') as
            | HTMLButtonElement
            | null;
          if (!applyBtn) return;
          const modal = ensureParachuteModal();
          const select = modal.querySelector('select[data-field="parachute_modal_select"]') as
            | HTMLSelectElement
            | null;
          const parachuteId = String(select?.value || "");
          if (!parachuteId) return;
          const componentId = String(modal.getAttribute("data-target-component-id") || "");
          if (!componentId) return;
          const componentNode = additionalList?.querySelector(
            `.module-r-additional-component[data-component-id="${componentId}"]`
          ) as HTMLElement | null;
          if (!componentNode) return;
          applyParachuteSelectionToComponent(componentNode, parachuteId);
          closeParachuteModal();
          const tube = componentNode.closest(".module-r-additional-tube") as HTMLElement | null;
          const tubeIndex = Number(tube?.getAttribute("data-tube") || "0");
          if (Number.isFinite(tubeIndex) && tubeIndex > 0) updateAdditionalPreview(tubeIndex);
          persistAdditionalDraft();
        });
        additionalList?.addEventListener("input", (event) => {
          const target = event.target as HTMLElement | null;
          const component = target?.closest(".module-r-additional-component") as HTMLElement | null;
          const overrideToggle = component?.querySelector('input[data-field="override_active"]') as
            | HTMLInputElement
            | null;
          const overrideField = component?.querySelector('[data-override-mass]') as HTMLElement | null;
          if (overrideToggle && overrideField) {
            overrideField.style.display = overrideToggle.checked ? "grid" : "none";
          }
          const tube = target?.closest(".module-r-additional-tube") as HTMLElement | null;
          const tubeIndex = Number(tube?.getAttribute("data-tube") || "0");
          if (Number.isFinite(tubeIndex) && tubeIndex > 0) {
            updateAdditionalPreview(tubeIndex);
          }
          persistAdditionalDraft();
        });
        additionalList?.addEventListener("change", (event) => {
          const target = event.target as HTMLElement | null;
          const component = target?.closest(".module-r-additional-component") as HTMLElement | null;
          const typeSelect = component?.querySelector('select[data-field="type"]') as
            | HTMLSelectElement
            | null;
          if (component && typeSelect) {
            const isParachute = typeSelect.value === "parachute";
            const picker = component.querySelector('[data-parachute-picker]') as HTMLElement | null;
            const dragField = component.querySelector('[data-parachute-drag]') as HTMLElement | null;
            if (picker) picker.style.display = isParachute ? "grid" : "none";
            if (dragField) dragField.style.display = isParachute ? "grid" : "none";
          }
          const overrideToggle = component?.querySelector('input[data-field="override_active"]') as
            | HTMLInputElement
            | null;
          const overrideField = component?.querySelector('[data-override-mass]') as HTMLElement | null;
          if (overrideToggle && overrideField) {
            overrideField.style.display = overrideToggle.checked ? "grid" : "none";
          }
          const tube = target?.closest(".module-r-additional-tube") as HTMLElement | null;
          const tubeIndex = Number(tube?.getAttribute("data-tube") || "0");
          if (Number.isFinite(tubeIndex) && tubeIndex > 0) {
            updateAdditionalPreview(tubeIndex);
          }
          persistAdditionalDraft();
        });

        additionalSave?.addEventListener("click", () => {
          if (!additionalList) return;
          const components = Array.from(
            additionalList.querySelectorAll(".module-r-additional-component")
          );
          if (!components.length) {
            setStatus("ADD AT LEAST ONE COMPONENT PER TUBE.");
            return;
          }
          const allValid = components.every((component) => {
            const nameInput = component.querySelector('input[data-field="name"]') as
              | HTMLInputElement
              | null;
            const typeSelect = component.querySelector('select[data-field="type"]') as
              | HTMLSelectElement
              | null;
            const massInput = component.querySelector('input[data-field="mass"]') as
              | HTMLInputElement
              | null;
            const overrideToggle = component.querySelector('input[data-field="override_active"]') as
              | HTMLInputElement
              | null;
            const overrideMassInput = component.querySelector('input[data-field="override_mass"]') as
              | HTMLInputElement
              | null;
            const dragInput = component.querySelector('input[data-field="drag"]') as
              | HTMLInputElement
              | null;
            const nameValid = String(nameInput?.value || "").trim().length > 0;
            const typeValid = Boolean(typeSelect?.value);
            const massValue = Number(massInput?.value);
            const massValid = Number.isFinite(massValue) && massValue >= 0;
            const overrideActive = Boolean(overrideToggle?.checked);
            const overrideMass = Number(overrideMassInput?.value);
            const overrideValid =
              !overrideActive || (Number.isFinite(overrideMass) && overrideMass >= 0);
            const isParachute = String(typeSelect?.value || "") === "parachute";
            const dragValue = Number(dragInput?.value);
            const dragValid = !isParachute || (Number.isFinite(dragValue) && dragValue > 0);
            return nameValid && typeValid && massValid && overrideValid && dragValid;
          });
          if (!allValid) {
            setStatus("COMPLETE ALL ADDITIONAL COMPONENT FIELDS BEFORE SAVING.");
            return;
          }
          const tubeCount = Number(
            window.localStorage.getItem("arx_module_r_additional_count") || "0"
          );
          const tubes = Array.from({ length: tubeCount }, (_, idx) => {
            const tubeIndex = idx + 1;
            const container = additionalList.querySelector(
              `.module-r-additional-components[data-tube="${tubeIndex}"]`
            ) as HTMLElement | null;
            const tubeComponents = Array.from(
              container?.querySelectorAll(".module-r-additional-component") || []
            ).map((component) => {
              const nameInput = component.querySelector('input[data-field="name"]') as
                | HTMLInputElement
                | null;
              const typeSelect = component.querySelector('select[data-field="type"]') as
                | HTMLSelectElement
                | null;
              const massInput = component.querySelector('input[data-field="mass"]') as
                | HTMLInputElement
                | null;
              const overrideToggle = component.querySelector('input[data-field="override_active"]') as
                | HTMLInputElement
                | null;
              const overrideMassInput = component.querySelector('input[data-field="override_mass"]') as
                | HTMLInputElement
                | null;
              const dragInput = component.querySelector('input[data-field="drag"]') as
                | HTMLInputElement
                | null;
              const parachuteMaterialInput = component.querySelector(
                'input[data-field="parachute_material"]'
              ) as HTMLInputElement | null;
              const parachuteDisplayInput = component.querySelector(
                'input[data-field="parachute_display"]'
              ) as HTMLInputElement | null;
              return {
                name: String(nameInput?.value || "").trim(),
                type: String(typeSelect?.value || ""),
                mass_lb: Number(massInput?.value || 0),
                drag_coefficient: Number(dragInput?.value || 0),
                parachute_material: String(parachuteMaterialInput?.value || "Nylon"),
                parachute_library_id: String(component.getAttribute("data-parachute-id") || ""),
                parachute_model: String(parachuteDisplayInput?.value || ""),
                is_override_active: Boolean(overrideToggle?.checked),
                manual_override_mass_lb: Number(overrideMassInput?.value || 0),
              };
            });
            return { tube: tubeIndex, components: tubeComponents };
          });
          window.localStorage.setItem("arx_module_r_additional_tubes", JSON.stringify(tubes));
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          window.localStorage.setItem("arx_module_r_body_additional_done", "true");
          updateCardStates();
          window.alert("Additional Tubes saved.");
          showPage("body");
          setStatus("ADDITIONAL TUBES SAVED.");
        });

        additionalClear?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_additional_owned");
          window.localStorage.setItem("arx_module_r_body_additional_done", "false");
          window.localStorage.removeItem("arx_module_r_additional_count");
          window.localStorage.removeItem("arx_module_r_additional_tubes");
          if (additionalCountInput) additionalCountInput.value = "";
          if (additionalList) additionalList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          showPage("additional-tubes");
          setStatus("ADDITIONAL TUBES CLEARED.");
        });

        additionalClearIndex?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_additional_owned");
          window.localStorage.setItem("arx_module_r_body_additional_done", "false");
          window.localStorage.removeItem("arx_module_r_additional_count");
          window.localStorage.removeItem("arx_module_r_additional_tubes");
          if (additionalCountInput) additionalCountInput.value = "";
          if (additionalList) additionalList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("ADDITIONAL TUBES CLEARED.");
        });

        bulkheadNext?.addEventListener("click", () => {
          if (!bulkheadCountInput || !bulkheadList) return;
          const count = Number(bulkheadCountInput.value);
          if (!Number.isFinite(count) || count < 1 || count > 12) {
            setStatus("ENTER 1-12 BULKHEADS.");
            return;
          }
          window.localStorage.setItem("arx_module_r_bulkhead_count", String(count));
          const savedBulkheads = JSON.parse(
            window.localStorage.getItem("arx_module_r_bulkheads") || "[]"
          ) as Array<{
            outer_diameter_in?: number;
            thickness_in?: number;
            position_in?: number;
            material?: string;
          }>;
          const bulkheadRows: string[] = [];
          for (let i = 1; i <= count; i += 1) {
            const saved = savedBulkheads[i - 1] || {};
            bulkheadRows.push(`
              <div class="module-r-fin-row module-r-bulkhead-row" data-bulkhead-row="${i}">
                <div class="module-r-fin-fields">
                  <div class="module-r-finset-title">BULKHEAD ${i}</div>
                  <div class="module-r-fin-fields-horizontal">
                    <div class="arx-field">
                      <input type="number" name="bulkhead_outer_diameter_${i}" placeholder=" " min="0" step="any" value="${Number(saved.outer_diameter_in || 0) > 0 ? Number(saved.outer_diameter_in) : ""}" />
                      <label>OUTER DIAMETER (IN)</label>
                    </div>
                    <div class="arx-field">
                      <input type="number" name="bulkhead_thickness_${i}" placeholder=" " min="0" step="any" value="${Number(saved.thickness_in || 0) > 0 ? Number(saved.thickness_in) : ""}" />
                      <label>THICKNESS (IN)</label>
                    </div>
                    <div class="arx-field">
                      <input type="number" name="bulkhead_position_${i}" placeholder=" " min="0" step="any" value="${Number(saved.position_in || 0) >= 0 ? Number(saved.position_in || 0) : 0}" />
                      <label>POSITION FROM BASE (IN)</label>
                    </div>
                    <div class="arx-field">
                      <select name="bulkhead_material_detail_${i}">
                        ${MODULE_R_FULL_MATERIAL_OPTIONS_HTML}
                      </select>
                      <label>BULKHEAD MATERIAL</label>
                    </div>
                  </div>
                </div>
                <div class="module-r-fin-preview-grid">
                  <div class="module-r-fin-preview-title">B${i} GRID</div>
                  <svg class="module-r-fin-preview-svg" data-bulkhead-preview="${i}" viewBox="0 0 240 130" preserveAspectRatio="xMidYMid meet">
                    <defs>
                      <pattern id="bulkhead-grid-${i}" width="12" height="12" patternUnits="userSpaceOnUse">
                        <path d="M 12 0 L 0 0 0 12" fill="none" stroke="rgba(0,243,255,0.25)" stroke-width="1" />
                      </pattern>
                    </defs>
                    <rect x="0" y="0" width="240" height="130" fill="url(#bulkhead-grid-${i})" />
                    <path data-bulkhead-shape="${i}" d="M 72 66 a 32 32 0 1 0 64 0 a 32 32 0 1 0 -64 0 M 88 66 a 16 16 0 1 1 32 0 a 16 16 0 1 1 -32 0" fill="rgba(0,243,255,0.22)" stroke="rgba(255,215,0,0.92)" stroke-width="2" fill-rule="evenodd" />
                  </svg>
                </div>
              </div>
            `);
          }
          bulkheadList.innerHTML = bulkheadRows.join("");
          for (let i = 1; i <= count; i += 1) {
            ["bulkhead_outer_diameter", "bulkhead_thickness", "bulkhead_position"].forEach((key) => {
              bulkheadList
                .querySelector(`input[name="${key}_${i}"]`)
                ?.addEventListener("input", () => updateBulkheadPreview(i));
            });
            const materialSelect = bulkheadList.querySelector(
              `select[name="bulkhead_material_detail_${i}"]`
            ) as HTMLSelectElement | null;
            const saved = savedBulkheads[i - 1];
            if (materialSelect && saved?.material) materialSelect.value = saved.material;
            materialSelect?.addEventListener("change", () => {
              updateBulkheadPreview(i);
              persistBulkheadDraft();
            });
            updateBulkheadPreview(i);
            ["bulkhead_outer_diameter", "bulkhead_thickness", "bulkhead_position"].forEach((key) => {
              bulkheadList
                .querySelector(`input[name="${key}_${i}"]`)
                ?.addEventListener("input", persistBulkheadDraft);
            });
          }
          persistBulkheadDraft();
          showPage("bulkheads-detail");
        });

        bulkheadsSave?.addEventListener("click", () => {
          if (!bulkheadList) return;
          const count = Number(bulkheadCountInput?.value || "0");
          if (!Number.isFinite(count) || count < 1) {
            setStatus("ENTER BULKHEAD COUNT.");
            return;
          }
          const bulkheads = Array.from({ length: count }, (_, idx) => {
            const i = idx + 1;
            const getNumber = (name: string, fallback = 0) => {
              const input = bulkheadList.querySelector(`input[name="${name}_${i}"]`) as
                | HTMLInputElement
                | null;
              const value = Number(input?.value ?? fallback);
              return Number.isFinite(value) ? value : fallback;
            };
            const getSelect = (name: string) =>
              bulkheadList.querySelector(`select[name="${name}_${i}"]`) as
                | HTMLSelectElement
                | null;
            return {
              outer_diameter_in: getNumber("bulkhead_outer_diameter", 0),
              thickness_in: getNumber("bulkhead_thickness", 0),
              position_in: getNumber("bulkhead_position", 0),
              material: getSelect("bulkhead_material_detail")?.value || "Cardboard",
            };
          });
          const hasInvalid = bulkheads.some(
            (item) =>
              !Number.isFinite(item.outer_diameter_in) ||
              item.outer_diameter_in <= 0 ||
              !Number.isFinite(item.thickness_in) ||
              item.thickness_in <= 0 ||
              !Number.isFinite(item.position_in) ||
              item.position_in < 0 ||
              !item.material
          );
          if (hasInvalid) {
            setStatus("COMPLETE ALL BULKHEAD FIELDS BEFORE SAVING.");
            return;
          }
          window.localStorage.setItem("arx_module_r_bulkheads", JSON.stringify(bulkheads));
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "true");
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          window.alert("Bulkheads saved.");
          showPage("body");
          setStatus("BULKHEADS SAVED.");
        });

        bulkheadsClear?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_bulkheads_owned");
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "false");
          window.localStorage.removeItem("arx_module_r_bulkhead_count");
          window.localStorage.removeItem("arx_module_r_bulkheads");
          if (bulkheadCountInput) bulkheadCountInput.value = "";
          if (bulkheadList) bulkheadList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          showPage("bulkheads");
          setStatus("BULKHEADS CLEARED.");
        });

        bulkheadsClearIndex?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_bulkheads_owned");
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "false");
          window.localStorage.removeItem("arx_module_r_bulkhead_count");
          window.localStorage.removeItem("arx_module_r_bulkheads");
          if (bulkheadCountInput) bulkheadCountInput.value = "";
          if (bulkheadList) bulkheadList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("BULKHEADS CLEARED.");
        });

        saveNoseBtn?.addEventListener("click", () => {
          const lengthInput = moduleR.querySelector('input[name="nose_length_in"]') as
            | HTMLInputElement
            | null;
          const typeSelect = moduleR.querySelector('select[name="nose_type"]') as
            | HTMLSelectElement
            | null;
          const materialSelect = moduleR.querySelector('select[name="nose_material"]') as
            | HTMLSelectElement
            | null;
          const lengthValue = Number(lengthInput?.value);
          if (!Number.isFinite(lengthValue) || lengthValue <= 0) {
            setStatus("ENTER NOSE HEIGHT.");
            return;
          }
          if (!typeSelect?.value || !materialSelect?.value) {
            setStatus("SELECT NOSE TYPE AND MATERIAL.");
            return;
          }
          window.localStorage.setItem(
            "arx_module_r_nose_cone",
            JSON.stringify({
              length_in: lengthValue,
              profile: typeSelect.value,
              material: materialSelect.value,
            })
          );
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          window.localStorage.setItem("arx_module_r_nose_done", "true");
          updateCardStates();
          window.alert("Nose Cone saved.");
          showPage("manual");
          setStatus("NOSE CONE SAVED.");
        });

        noseClearBtn?.addEventListener("click", () => {
          const lengthInput = moduleR.querySelector('input[name="nose_length_in"]') as
            | HTMLInputElement
            | null;
          const typeSelect = moduleR.querySelector('select[name="nose_type"]') as
            | HTMLSelectElement
            | null;
          const materialSelect = moduleR.querySelector('select[name="nose_material"]') as
            | HTMLSelectElement
            | null;
          if (lengthInput) lengthInput.value = "";
          if (typeSelect) typeSelect.selectedIndex = 0;
          if (materialSelect) materialSelect.selectedIndex = 0;
          window.localStorage.removeItem("arx_module_r_nose_cone");
          window.localStorage.setItem("arx_module_r_nose_done", "false");
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("NOSE CONE CLEARED.");
        });

        const finTypeOptions = [
          { value: "trapezoidal", label: "Trapezoidal" },
          { value: "elliptical", label: "Elliptical" },
          { value: "free_form", label: "Free Form" },
          { value: "tube_fin", label: "Tube Fin Sets" },
        ] as const;
        const noseLengthInput = moduleR.querySelector('input[name="nose_length_in"]') as
          | HTMLInputElement
          | null;
        const noseTypeSelect = moduleR.querySelector('select[name="nose_type"]') as
          | HTMLSelectElement
          | null;
        const noseMaterialSelect = moduleR.querySelector('select[name="nose_material"]') as
          | HTMLSelectElement
          | null;
        const savedNoseRaw = window.localStorage.getItem("arx_module_r_nose_cone");
        if (savedNoseRaw) {
          try {
            const savedNose = JSON.parse(savedNoseRaw) as {
              length_in?: number;
              profile?: string;
              material?: string;
            };
            if (noseLengthInput && Number(savedNose.length_in || 0) > 0) {
              noseLengthInput.value = String(savedNose.length_in);
            }
            if (noseTypeSelect && savedNose.profile) noseTypeSelect.value = savedNose.profile;
            if (noseMaterialSelect && savedNose.material) noseMaterialSelect.value = savedNose.material;
          } catch {
            // no-op
          }
        }
        noseLengthInput?.addEventListener("input", updateNosePreview);
        noseTypeSelect?.addEventListener("change", updateNosePreview);
        updateNosePreview();

        const crossSectionSelect = (index: number) => `
          <div class="arx-field">
            <select name="fin_cross_section_${index}">
              <option value="square">Square</option>
              <option value="rounded">Rounded</option>
              <option value="airfoil">Airfoil</option>
            </select>
            <label>CROSS SECTION</label>
          </div>
        `;

        const placementBlock = (index: number) => `
          <div class="module-r-fin-block">
            <div class="module-r-fin-block-title">Placement</div>
            <div class="module-r-fin-fields-compact">
              <div class="arx-field">
                <select name="fin_position_relative_${index}">
                  <option value="bottom">Bottom of the parent component</option>
                  <option value="top">Top of the parent component</option>
                </select>
                <label>POSITION RELATIVE TO</label>
              </div>
              <div class="arx-field">
                <input type="number" name="fin_plus_offset_${index}" placeholder=" " min="0" step="any" value="0" />
                <label>PLUS (IN)</label>
              </div>
              <div class="arx-field">
                <input type="number" name="fin_rotation_${index}" placeholder=" " min="0" step="any" value="0" />
                <label>FIN ROTATION (DEG)</label>
              </div>
            </div>
          </div>
        `;

        const materialBlock = (index: number) => `
          <div class="module-r-fin-block">
            <div class="module-r-fin-block-title">Material</div>
            <div class="module-r-fin-fields-compact">
              <div class="arx-field">
                <select name="fin_material_${index}">
                  ${MODULE_R_FULL_MATERIAL_OPTIONS_HTML}
                </select>
                <label>MATERIAL</label>
              </div>
              <div class="arx-field">
                <select name="fin_finish_${index}">
                  <option value="regular_paint">Regular paint</option>
                  <option value="polished">Polished</option>
                  <option value="matte">Matte</option>
                </select>
                <label>COMPONENT FINISH</label>
              </div>
            </div>
          </div>
        `;

        const filletBlock = (index: number) => `
          <div class="module-r-fin-block">
            <div class="module-r-fin-block-title">Root Fillets</div>
            <div class="module-r-fin-fields-compact">
              <div class="arx-field">
                <input type="number" name="fin_fillet_radius_${index}" placeholder=" " min="0" step="any" value="0" />
                <label>FILLET RADIUS (IN)</label>
              </div>
              <div class="arx-field">
                <select name="fin_fillet_material_${index}">
                  ${MODULE_R_FULL_MATERIAL_OPTIONS_HTML}
                </select>
                <label>FILLET MATERIAL</label>
              </div>
            </div>
          </div>
        `;

        const freeformShapeBlock = (index: number) => `
          <div class="module-r-fin-pages" data-fin-pages="${index}">
            <div class="module-r-fin-page-nav">
              <button type="button" class="module-r-fin-page-btn is-active" data-fin-page-btn="${index}" data-page="general">General</button>
              <button type="button" class="module-r-fin-page-btn" data-fin-page-btn="${index}" data-page="shape">Shape</button>
            </div>
            <div class="module-r-fin-page" data-fin-page="${index}" data-page="general">
              <div class="module-r-fin-block">
                <div class="module-r-fin-block-title">General</div>
                <div class="module-r-fin-fields-compact">
                  <div class="arx-field"><input type="number" name="fin_count_${index}" placeholder=" " min="2" step="1" value="3" /><label>NUMBER OF FINS</label></div>
                  <div class="arx-field"><input type="number" name="fin_cant_${index}" placeholder=" " min="0" step="any" value="0" /><label>FIN CANT (DEG)</label></div>
                  ${crossSectionSelect(index)}
                  <div class="arx-field"><input type="number" name="fin_thickness_${index}" placeholder=" " min="0" step="any" value="0.12" /><label>THICKNESS (IN)</label></div>
                </div>
              </div>
              ${placementBlock(index)}
              ${materialBlock(index)}
              ${filletBlock(index)}
            </div>
            <div class="module-r-fin-page is-hidden" data-fin-page="${index}" data-page="shape">
              <div class="module-r-fin-block">
                <div class="module-r-fin-block-title">Freeform Shape Coordinates</div>
                <div class="module-r-freeform-shape-panel" data-freeform-panel="${index}">
                  <div class="module-r-freeform-table">
                    <div class="module-r-freeform-head">X / in</div><div class="module-r-freeform-head">Y / in</div>
                    <input type="number" name="free_x_1_${index}" value="0" step="any" /><input type="number" name="free_y_1_${index}" value="0" step="any" />
                    <input type="number" name="free_x_2_${index}" value="0.984" step="any" /><input type="number" name="free_y_2_${index}" value="1.969" step="any" />
                    <input type="number" name="free_x_3_${index}" value="2.953" step="any" /><input type="number" name="free_y_3_${index}" value="1.969" step="any" />
                    <input type="number" name="free_x_4_${index}" value="1.969" step="any" /><input type="number" name="free_y_4_${index}" value="0" step="any" />
                  </div>
                  <svg class="module-r-freeform-svg" data-freeform-svg="${index}" viewBox="0 0 260 170" preserveAspectRatio="xMidYMid meet">
                    <defs>
                      <pattern id="free-grid-${index}" width="10" height="10" patternUnits="userSpaceOnUse">
                        <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(80,120,255,0.30)" stroke-width="1" />
                      </pattern>
                    </defs>
                    <rect x="0" y="0" width="260" height="170" fill="url(#free-grid-${index})" />
                    <path data-freeform-shape="${index}" d="M 25 145 L 85 28 L 235 28 L 170 145 Z" fill="none" stroke="rgba(255,255,255,0.95)" stroke-width="2" />
                      <g data-freeform-handles="${index}">
                        <circle data-freeform-handle="${index}" data-point="1" cx="25" cy="145" r="6" />
                        <circle data-freeform-handle="${index}" data-point="2" cx="85" cy="28" r="6" />
                        <circle data-freeform-handle="${index}" data-point="3" cx="235" cy="28" r="6" />
                        <circle data-freeform-handle="${index}" data-point="4" cx="170" cy="145" r="6" />
                      </g>
                  </svg>
                  <div class="module-r-freeform-actions">
                    <button type="button" class="arx-btn" data-action="freeform-scale">Scale Fin</button>
                    <button type="button" class="arx-btn" data-action="freeform-import">Import from image</button>
                    <button type="button" class="arx-btn" data-action="freeform-export">Export CSV</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;

        const renderFinTypeFields = (type: string, index: number) => {
          const t = String(type || "trapezoidal");
          if (t === "free_form") {
            return `<div class="module-r-fin-type-fields-inner">${freeformShapeBlock(index)}</div>`;
          }
          if (t === "elliptical") {
            return `
              <div class="module-r-fin-type-fields-inner">
                <div class="module-r-fin-block">
                  <div class="module-r-fin-block-title">General</div>
                  <div class="module-r-fin-fields-compact">
                    <div class="arx-field"><input type="number" name="fin_count_${index}" placeholder=" " min="2" step="1" value="3" /><label>NUMBER OF FINS</label></div>
                    <div class="arx-field"><input type="number" name="fin_cant_${index}" placeholder=" " min="0" step="any" value="0" /><label>FIN CANT (DEG)</label></div>
                    <div class="arx-field"><input type="number" name="fin_root_${index}" placeholder=" " min="0" step="any" value="2" /><label>ROOT CHORD (IN)</label></div>
                    <div class="arx-field"><input type="number" name="fin_height_${index}" placeholder=" " min="0" step="any" value="2" /><label>HEIGHT (IN)</label></div>
                    ${crossSectionSelect(index)}
                    <div class="arx-field"><input type="number" name="fin_thickness_${index}" placeholder=" " min="0" step="any" value="0.12" /><label>THICKNESS (IN)</label></div>
                  </div>
                </div>
                ${placementBlock(index)}
                ${materialBlock(index)}
                ${filletBlock(index)}
              </div>
            `;
          }
          if (t === "tube_fin") {
            return `
              <div class="module-r-fin-type-fields-inner">
                <div class="module-r-fin-block">
                  <div class="module-r-fin-block-title">General</div>
                  <div class="module-r-fin-fields-compact">
                    <div class="arx-field"><input type="number" name="fin_count_${index}" placeholder=" " min="2" step="1" value="6" /><label>NUMBER OF FINS</label></div>
                    <div class="arx-field"><input type="number" name="tube_length_${index}" placeholder=" " min="0" step="any" value="4" /><label>LENGTH (IN)</label></div>
                    <div class="arx-field"><input type="number" name="tube_outer_diameter_${index}" placeholder=" " min="0" step="any" value="2" /><label>OUTER DIAMETER (IN)</label></div>
                    <label class="nav-link module-r-fin-checkbox"><input type="checkbox" name="tube_auto_inner_${index}" checked />Automatic</label>
                    <div class="arx-field"><input type="number" name="tube_inner_diameter_${index}" placeholder=" " min="0" step="any" value="1.8" /><label>INNER DIAMETER (IN)</label></div>
                    <div class="arx-field"><input type="number" name="fin_thickness_${index}" placeholder=" " min="0" step="any" value="0.08" /><label>THICKNESS (IN)</label></div>
                  </div>
                </div>
                ${placementBlock(index)}
                ${materialBlock(index)}
              </div>
            `;
          }
          return `
            <div class="module-r-fin-type-fields-inner">
              <div class="module-r-fin-block">
                <div class="module-r-fin-block-title">General</div>
                <div class="module-r-fin-fields-compact">
                  <div class="arx-field"><input type="number" name="fin_count_${index}" placeholder=" " min="2" step="1" value="3" /><label>NUMBER OF FINS</label></div>
                  <div class="arx-field"><input type="number" name="fin_cant_${index}" placeholder=" " min="0" step="any" value="0" /><label>FIN CANT (DEG)</label></div>
                  <div class="arx-field"><input type="number" name="fin_root_${index}" placeholder=" " min="0" step="any" value="2" /><label>ROOT CHORD (IN)</label></div>
                  <div class="arx-field"><input type="number" name="fin_tip_${index}" placeholder=" " min="0" step="any" value="2" /><label>TIP CHORD (IN)</label></div>
                  <div class="arx-field"><input type="number" name="fin_span_${index}" placeholder=" " min="0" step="any" value="1.2" /><label>HEIGHT (IN)</label></div>
                  <div class="arx-field"><input type="number" name="fin_sweep_${index}" placeholder=" " min="0" step="any" value="1" /><label>SWEEP LENGTH (IN)</label></div>
                  <div class="arx-field"><input type="number" name="fin_sweep_angle_${index}" placeholder=" " min="0" step="any" value="39.8" /><label>SWEEP ANGLE (DEG)</label></div>
                  ${crossSectionSelect(index)}
                  <div class="arx-field"><input type="number" name="fin_thickness_${index}" placeholder=" " min="0" step="any" value="0.12" /><label>THICKNESS (IN)</label></div>
                </div>
              </div>
              ${placementBlock(index)}
              ${materialBlock(index)}
              ${filletBlock(index)}
            </div>
          `;
        };

        const updateFreeformShape = (index: number) => {
          if (!finsList) return;
          const svg = finsList.querySelector(
            `.module-r-freeform-svg[data-freeform-svg="${index}"]`
          ) as SVGSVGElement | null;
          const path = finsList.querySelector(
            `[data-freeform-shape="${index}"]`
          ) as SVGPathElement | null;
          if (!svg || !path) return;
          const handles = Array.from(
            finsList.querySelectorAll(
              `[data-freeform-handle="${index}"]`
            )
          ) as SVGCircleElement[];
          const getPoint = (n: number, axis: "x" | "y", fallback: number) => {
            const input = finsList.querySelector(
              `input[name="free_${axis}_${n}_${index}"]`
            ) as HTMLInputElement | null;
            const value = Number(input?.value ?? fallback);
            return Number.isFinite(value) ? value : fallback;
          };
          const pts = [
            { x: getPoint(1, "x", 0), y: getPoint(1, "y", 0) },
            { x: getPoint(2, "x", 1), y: getPoint(2, "y", 2) },
            { x: getPoint(3, "x", 3), y: getPoint(3, "y", 2) },
            { x: getPoint(4, "x", 2), y: getPoint(4, "y", 0) },
          ];
          const minX = Math.min(...pts.map((p) => p.x));
          const maxX = Math.max(...pts.map((p) => p.x));
          const minY = Math.min(...pts.map((p) => p.y));
          const maxY = Math.max(...pts.map((p) => p.y));
          const w = Math.max(maxX - minX, 0.1);
          const h = Math.max(maxY - minY, 0.1);
          const pad = 18;
          const width = 260;
          const height = 170;
          const scale = Math.min((width - pad * 2) / w, (height - pad * 2) / h);
          const toX = (v: number) => pad + (v - minX) * scale;
          const toY = (v: number) => height - (pad + (v - minY) * scale);
          svg.setAttribute("data-min-x", String(minX));
          svg.setAttribute("data-min-y", String(minY));
          svg.setAttribute("data-scale", String(scale));
          svg.setAttribute("data-pad", String(pad));
          svg.setAttribute("data-h", String(height));
          path.setAttribute(
            "d",
            `M ${toX(pts[0].x)} ${toY(pts[0].y)} L ${toX(pts[1].x)} ${toY(pts[1].y)} L ${toX(
              pts[2].x
            )} ${toY(pts[2].y)} L ${toX(pts[3].x)} ${toY(pts[3].y)} Z`
          );
          handles.forEach((handle) => {
            const point = Number(handle.getAttribute("data-point") || "1");
            const pt = pts[Math.max(0, Math.min(3, point - 1))];
            handle.setAttribute("cx", String(toX(pt.x)));
            handle.setAttribute("cy", String(toY(pt.y)));
          });
        };

        const updateFinPreview = (index: number) => {
          if (!finsList) return;
          const svg = finsList.querySelector(
            `.module-r-fin-preview-svg[data-fin-preview="${index}"]`
          ) as SVGSVGElement | null;
          if (!svg) return;
          const shape = svg.querySelector('[data-shape="fin"]') as SVGPathElement | null;
          if (!shape) return;

          const getNumber = (name: string, fallback: number, allowZero = false) => {
            const input = finsList.querySelector(`input[name="${name}_${index}"]`) as
              | HTMLInputElement
              | null;
            const value = Number(input?.value ?? fallback);
            if (!Number.isFinite(value)) return fallback;
            if (allowZero) return value;
            return value > 0 ? value : fallback;
          };
          const getType = () =>
            (
              finsList.querySelector(`select[name="fin_type_${index}"]`) as
                | HTMLSelectElement
                | null
            )?.value || "trapezoidal";

          const type = getType();
          const root = getNumber("fin_root", 6);
          const tip = getNumber("fin_tip", 3);
          const span = getNumber("fin_span", getNumber("fin_height", 4));
          const sweep = getNumber("fin_sweep", 1, true);
          const tubeLength = getNumber("tube_length", 4);
          const tubeOuter = getNumber("tube_outer_diameter", 2);
          const recommendationNode = finsList.querySelector(
            `[data-fin-recommendation="${index}"]`
          ) as HTMLElement | null;
          const rocketDiameterIn = Math.max(
            0,
            Number(window.localStorage.getItem("arx_module_r_width") || "0")
          );
          if (recommendationNode) {
            if (rocketDiameterIn > 0) {
              const recommendedSpanIn = rocketDiameterIn * 3;
              const tolerance = Math.max(0.15, recommendedSpanIn * 0.08);
              const proportional = Math.abs(span - recommendedSpanIn) <= tolerance;
              recommendationNode.textContent = proportional
                ? `PROPORTIONAL | RECOMMENDED SPAN ${recommendedSpanIn.toFixed(2)} IN`
                : `RECOMMENDED SPAN ${recommendedSpanIn.toFixed(2)} IN (1:3 BODY:SPAN)`;
              recommendationNode.classList.toggle("is-good", proportional);
            } else {
              recommendationNode.textContent = "";
              recommendationNode.classList.remove("is-good");
            }
          }

          const width = 240;
          const height = 130;
          const pad = 14;
          const shapeWidth = Math.max(root, sweep + tip, 0.5);
          const shapeHeight = Math.max(span, 0.5);
          const scale = Math.min(
            (width - pad * 2) / Math.max(shapeWidth, 0.5),
            (height - pad * 2) / Math.max(shapeHeight, 0.5)
          );
          const x = (v: number) => pad + v * scale;
          const y = (v: number) => height - (pad + v * scale);
          if (type === "trapezoidal") {
            const p0 = `${x(0)},${y(0)}`;
            const p1 = `${x(root)},${y(0)}`;
            const p2 = `${x(sweep + tip)},${y(span)}`;
            const p3 = `${x(sweep)},${y(span)}`;
            shape.setAttribute("d", `M ${p0} L ${p1} L ${p2} L ${p3} Z`);
            return;
          }

          if (type === "elliptical") {
            const cx = x(shapeWidth * 0.5);
            const cy = y(shapeHeight * 0.5);
            const rx = Math.max((shapeWidth * scale) / 2, 8);
            const ry = Math.max((shapeHeight * scale) / 2, 8);
            shape.setAttribute("d", `M ${cx - rx},${cy} a ${rx},${ry} 0 1,0 ${rx * 2},0 a ${rx},${ry} 0 1,0 -${rx * 2},0`);
            return;
          }

          if (type === "tube_fin") {
            const w = Math.max(tubeLength, 0.5);
            const h = Math.max(tubeOuter, 0.5);
            const innerInput = finsList.querySelector(
              `input[name="tube_inner_diameter_${index}"]`
            ) as HTMLInputElement | null;
            const innerRaw = Number(innerInput?.value ?? 0);
            const inner = Number.isFinite(innerRaw) ? Math.max(0, Math.min(innerRaw, h - 0.02)) : 0;
            const localScale = Math.min((width - pad * 2) / w, (height - pad * 2) / h);
            const rx = (h * localScale) * 0.5;
            const ry = rx;
            const rectW = w * localScale;
            const left = pad;
            const right = left + rectW;
            const top = (height - h * localScale) / 2;
            const bottom = top + h * localScale;
            let path = `M ${left + rx},${top} L ${right - rx},${top} A ${rx},${ry} 0 0,1 ${right - rx},${bottom} L ${
              left + rx
            },${bottom} A ${rx},${ry} 0 0,1 ${left + rx},${top} Z`;
            if (inner > 0.01) {
              const innerH = inner * localScale;
              const innerTop = (height - innerH) / 2;
              const innerBottom = innerTop + innerH;
              const innerRx = innerH * 0.5;
              path += ` M ${left + innerRx},${innerTop} L ${right - innerRx},${innerTop} A ${innerRx},${innerRx} 0 0,0 ${
                right - innerRx
              },${innerBottom} L ${left + innerRx},${innerBottom} A ${innerRx},${innerRx} 0 0,0 ${left + innerRx},${innerTop} Z`;
              shape.setAttribute("fill-rule", "evenodd");
            } else {
              shape.removeAttribute("fill-rule");
            }
            shape.setAttribute(
              "d",
              path
            );
            return;
          }

          if (type === "free_form") {
            const getFree = (axis: "x" | "y", n: number, fallback: number) => {
              const input = finsList.querySelector(
                `input[name="free_${axis}_${n}_${index}"]`
              ) as HTMLInputElement | null;
              const value = Number(input?.value ?? fallback);
              return Number.isFinite(value) ? value : fallback;
            };
            const pts = [
              { x: getFree("x", 1, 0), y: getFree("y", 1, 0) },
              { x: getFree("x", 2, 1), y: getFree("y", 2, 2) },
              { x: getFree("x", 3, 3), y: getFree("y", 3, 2) },
              { x: getFree("x", 4, 2), y: getFree("y", 4, 0) },
            ];
            const minX = Math.min(...pts.map((p) => p.x));
            const maxX = Math.max(...pts.map((p) => p.x));
            const minY = Math.min(...pts.map((p) => p.y));
            const maxY = Math.max(...pts.map((p) => p.y));
            const fw = Math.max(maxX - minX, 0.5);
            const fh = Math.max(maxY - minY, 0.5);
            const fs = Math.min((width - pad * 2) / fw, (height - pad * 2) / fh);
            const px = (v: number) => pad + (v - minX) * fs;
            const py = (v: number) => height - (pad + (v - minY) * fs);
            shape.setAttribute(
              "d",
              `M ${px(pts[0].x)} ${py(pts[0].y)} L ${px(pts[1].x)} ${py(pts[1].y)} L ${px(
                pts[2].x
              )} ${py(pts[2].y)} L ${px(pts[3].x)} ${py(pts[3].y)} Z`
            );
            updateFreeformShape(index);
            return;
          }

          const p0 = `${x(0)},${y(0)}`;
          const p1 = `${x(root * 0.8)},${y(0.15 * span)}`;
          const p2 = `${x(sweep + tip)},${y(span)}`;
          const p3 = `${x(sweep * 0.6)},${y(span * 0.85)}`;
          shape.setAttribute("d", `M ${p0} L ${p1} L ${p2} L ${p3} Z`);
        };

        const attachFinRowListeners = (index: number) => {
          if (!finsList) return;
          const typeSelect = finsList.querySelector(`select[name="fin_type_${index}"]`) as
            | HTMLSelectElement
            | null;
          const typeFields = finsList.querySelector(
            `.module-r-fin-type-fields[data-fin-type-fields="${index}"]`
          ) as HTMLElement | null;
          const row = finsList.querySelector(
            `.module-r-fin-row[data-fin-row="${index}"]`
          ) as HTMLElement | null;
          const freeformInputs = row
            ? Array.from(
                row.querySelectorAll(
                  `input[name^="free_x_"], input[name^="free_y_"]`
                )
              ) as HTMLInputElement[]
            : [];
          const redraw = () => updateFinPreview(index);
          const getPoint = (n: number, axis: "x" | "y", fallback: number) => {
            const input = row?.querySelector(
              `input[name="free_${axis}_${n}_${index}"]`
            ) as HTMLInputElement | null;
            const value = Number(input?.value ?? fallback);
            return Number.isFinite(value) ? value : fallback;
          };
          const setPoint = (n: number, axis: "x" | "y", value: number) => {
            const input = row?.querySelector(
              `input[name="free_${axis}_${n}_${index}"]`
            ) as HTMLInputElement | null;
            if (input) input.value = String(value);
          };
          const applyTubeAutoState = () => {
            const autoInner = row?.querySelector(
              `input[name="tube_auto_inner_${index}"]`
            ) as HTMLInputElement | null;
            const outerInput = row?.querySelector(
              `input[name="tube_outer_diameter_${index}"]`
            ) as HTMLInputElement | null;
            const thicknessInput = row?.querySelector(
              `input[name="fin_thickness_${index}"]`
            ) as HTMLInputElement | null;
            const innerInput = row?.querySelector(
              `input[name="tube_inner_diameter_${index}"]`
            ) as HTMLInputElement | null;
            if (!innerInput) return;
            const outer = Number(outerInput?.value ?? 0);
            const thickness = Math.max(0, Number(thicknessInput?.value ?? 0));
            const checked = Boolean(autoInner?.checked);
            innerInput.disabled = checked;
            if (checked && Number.isFinite(outer) && outer > 0) {
              const computed = Math.max(outer - 2 * Math.max(thickness, 0.01), 0.02);
              innerInput.value = String(Math.min(computed, outer - 0.01));
            }
            redraw();
          };
          const wireFreeformActions = () => {
            const scaleBtn = row?.querySelector(
              `[data-action="freeform-scale"]`
            ) as HTMLButtonElement | null;
            const exportBtn = row?.querySelector(
              `[data-action="freeform-export"]`
            ) as HTMLButtonElement | null;
            const importBtn = row?.querySelector(
              `[data-action="freeform-import"]`
            ) as HTMLButtonElement | null;
            const panel = row?.querySelector(
              `[data-freeform-panel="${index}"]`
            ) as HTMLElement | null;
            if (!panel) return;
            let fileInput = panel.querySelector(
              `input[type="file"][data-freeform-file="${index}"]`
            ) as HTMLInputElement | null;
            if (!fileInput) {
              fileInput = document.createElement("input");
              fileInput.type = "file";
              fileInput.accept = ".csv,text/csv";
              fileInput.style.display = "none";
              fileInput.setAttribute("data-freeform-file", String(index));
              panel.appendChild(fileInput);
            }
            scaleBtn!.onclick = () => {
              const points = [1, 2, 3, 4].map((n) => ({
                x: getPoint(n, "x", n === 3 ? 3 : n === 4 ? 2 : n - 1),
                y: getPoint(n, "y", n === 1 || n === 4 ? 0 : 2),
              }));
              const minX = Math.min(...points.map((p) => p.x));
              const maxX = Math.max(...points.map((p) => p.x));
              const minY = Math.min(...points.map((p) => p.y));
              const maxY = Math.max(...points.map((p) => p.y));
              const width = Math.max(maxX - minX, 0.0001);
              const height = Math.max(maxY - minY, 0.0001);
              const target = 3;
              const scale = target / Math.max(width, height);
              points.forEach((p, i) => {
                const nx = (p.x - minX) * scale;
                const ny = (p.y - minY) * scale;
                setPoint(i + 1, "x", Number(nx.toFixed(3)));
                setPoint(i + 1, "y", Number(ny.toFixed(3)));
              });
              redraw();
              updateFreeformShape(index);
              setStatus(`FREEFORM FIN ${index}: SCALED TO ${target} IN MAX EXTENT.`);
            };
            exportBtn!.onclick = () => {
              const rows = [
                "x_in,y_in",
                ...[1, 2, 3, 4].map((n) => `${getPoint(n, "x", 0)},${getPoint(n, "y", 0)}`),
              ].join("\n");
              const blob = new Blob([rows], { type: "text/csv;charset=utf-8;" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `module_r_freeform_fin_${index}.csv`;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
              setStatus(`FREEFORM FIN ${index}: CSV EXPORTED.`);
            };
            fileInput!.onchange = () => {
              const file = fileInput?.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = () => {
                const text = String(reader.result ?? "");
                const lines = text
                  .split(/\r?\n/)
                  .map((line) => line.trim())
                  .filter(Boolean);
                const parsed: Array<{ x: number; y: number }> = [];
                lines.forEach((line) => {
                  const clean = line.replace(/[;\t]/g, ",");
                  const [a, b] = clean.split(",").map((v) => Number(v.trim()));
                  if (Number.isFinite(a) && Number.isFinite(b)) parsed.push({ x: a, y: b });
                });
                if (parsed.length < 4) {
                  setStatus("FREEFORM CSV MUST CONTAIN AT LEAST 4 NUMERIC X,Y ROWS.");
                  return;
                }
                parsed.slice(0, 4).forEach((p, i) => {
                  setPoint(i + 1, "x", Number(p.x.toFixed(3)));
                  setPoint(i + 1, "y", Number(p.y.toFixed(3)));
                });
                redraw();
                updateFreeformShape(index);
                setStatus(`FREEFORM FIN ${index}: IMPORTED ${parsed.length} POINTS (FIRST 4 USED).`);
              };
              reader.readAsText(file);
              fileInput.value = "";
            };
            importBtn!.onclick = () => fileInput?.click();
          };
          const wireFreeformDrag = () => {
            const svg = row?.querySelector(
              `.module-r-freeform-svg[data-freeform-svg="${index}"]`
            ) as SVGSVGElement | null;
            if (!svg) return;
            const getGraphPointFromEvent = (ev: PointerEvent) => {
              const rect = svg.getBoundingClientRect();
              const sx = ((ev.clientX - rect.left) / Math.max(rect.width, 1)) * 260;
              const sy = ((ev.clientY - rect.top) / Math.max(rect.height, 1)) * 170;
              const minX = Number(svg.getAttribute("data-min-x") || "0");
              const minY = Number(svg.getAttribute("data-min-y") || "0");
              const scale = Number(svg.getAttribute("data-scale") || "1");
              const pad = Number(svg.getAttribute("data-pad") || "18");
              const h = Number(svg.getAttribute("data-h") || "170");
              const x = minX + (sx - pad) / Math.max(scale, 0.0001);
              const y = minY + ((h - sy) - pad) / Math.max(scale, 0.0001);
              return { x, y, sx, sy };
            };
            const nearestHandle = (sx: number, sy: number) => {
              const handles = Array.from(
                svg.querySelectorAll(`[data-freeform-handle="${index}"]`)
              ) as SVGCircleElement[];
              let bestPoint = 1;
              let bestDist = Number.POSITIVE_INFINITY;
              handles.forEach((handle) => {
                const hx = Number(handle.getAttribute("cx") || "0");
                const hy = Number(handle.getAttribute("cy") || "0");
                const d = Math.hypot(hx - sx, hy - sy);
                if (d < bestDist) {
                  bestDist = d;
                  bestPoint = Number(handle.getAttribute("data-point") || "1");
                }
              });
              return bestDist <= 24 ? bestPoint : null;
            };
            let dragPoint: number | null = null;
            const move = (ev: PointerEvent) => {
              if (dragPoint == null) return;
              ev.preventDefault();
              const p = getGraphPointFromEvent(ev);
              setPoint(dragPoint, "x", Number(p.x.toFixed(3)));
              setPoint(dragPoint, "y", Number(p.y.toFixed(3)));
              updateFreeformShape(index);
              redraw();
            };
            const stop = () => {
              dragPoint = null;
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", stop);
            };
            svg.onpointerdown = (ev: PointerEvent) => {
              const target = ev.target as Element | null;
              const directPoint = target?.getAttribute("data-point");
              if (directPoint) {
                dragPoint = Number(directPoint);
              } else {
                const p = getGraphPointFromEvent(ev);
                dragPoint = nearestHandle(p.sx, p.sy);
              }
              if (dragPoint == null) return;
              ev.preventDefault();
              window.addEventListener("pointermove", move);
              window.addEventListener("pointerup", stop);
            };
          };

          const wireFreeformTabs = () => {
            const pageButtons = row?.querySelectorAll(
              `[data-fin-page-btn="${index}"]`
            ) as NodeListOf<HTMLButtonElement> | undefined;
            const pages = row?.querySelectorAll(
              `[data-fin-page="${index}"]`
            ) as NodeListOf<HTMLElement> | undefined;
            pageButtons?.forEach((btn) => {
              btn.onclick = () => {
                const page = btn.getAttribute("data-page") || "general";
                pageButtons.forEach((b) => {
                  b.classList.toggle("is-active", b === btn);
                });
                pages?.forEach((p) => {
                  p.classList.toggle("is-hidden", p.getAttribute("data-page") !== page);
                });
              };
            });
          };

          row?.querySelectorAll("input, select").forEach((el) => {
            if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement) {
              el.addEventListener("input", redraw);
              el.addEventListener("change", redraw);
            }
          });
          freeformInputs.forEach((input) => {
            input.addEventListener("input", () => updateFreeformShape(index));
          });
          wireFreeformTabs();
          wireFreeformActions();
          wireFreeformDrag();
          applyTubeAutoState();
          row
            ?.querySelector(`input[name="tube_auto_inner_${index}"]`)
            ?.addEventListener("change", applyTubeAutoState);
          row
            ?.querySelector(`input[name="tube_outer_diameter_${index}"]`)
            ?.addEventListener("input", applyTubeAutoState);
          row
            ?.querySelector(`input[name="fin_thickness_${index}"]`)
            ?.addEventListener("input", applyTubeAutoState);

          if (typeSelect) {
            typeSelect.onchange = () => {
            const selectedType = typeSelect.value || "trapezoidal";
            if (typeFields) {
              typeFields.innerHTML = renderFinTypeFields(selectedType, index);
            }
            if (row) {
              row.setAttribute("data-fin-type", selectedType);
            }
            attachFinRowListeners(index);
            redraw();
            };
          }
          redraw();
          updateFreeformShape(index);
        };

        finsNextBtn?.addEventListener("click", () => {
          if (!finsCountInput || !finsList) return;
          const count = Number(finsCountInput.value);
          if (!Number.isFinite(count) || count < 1 || count > 8) {
            setStatus("ENTER 1-8 FIN SETS.");
            return;
          }
          const stageCount = Number(
            window.localStorage.getItem("arx_module_r_stage_count") || "1"
          );
          const additionalCount = Number(
            window.localStorage.getItem("arx_module_r_additional_count") || "0"
          );
          const parentOptions = [
            ...Array.from({ length: stageCount }, (_, i) => ({
              value: `stage-${i + 1}`,
              label: `Stage ${i + 1}`,
            })),
            ...Array.from({ length: additionalCount }, (_, i) => ({
              value: `additional-${i + 1}`,
              label: `Additional Tube ${i + 1}`,
            })),
          ];

          const finRowsHtml: string[] = [];
          for (let i = 1; i <= count; i += 1) {
            const optionsHtml = parentOptions
              .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
              .join("");
            finRowsHtml.push(`
              <div class="module-r-fin-row" data-fin-row="${i}" data-fin-type="trapezoidal">
                <div class="module-r-fin-fields">
                  <div class="module-r-finset-title">FIN SET ${i}</div>
                  <div class="module-r-fin-recommendation" data-fin-recommendation="${i}"></div>
                  <div class="module-r-fin-fields-horizontal">
                    <div class="arx-field">
                      <select name="fin_parent_${i}">${optionsHtml}</select>
                      <label>PARENT COMPONENT</label>
                    </div>
                    <div class="arx-field">
                      <select name="fin_type_${i}">
                        ${finTypeOptions
                          .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
                          .join("")}
                      </select>
                      <label>FIN TYPE</label>
                    </div>
                  </div>
                  <div class="module-r-fin-type-fields" data-fin-type-fields="${i}">
                    ${renderFinTypeFields("trapezoidal", i)}
                  </div>
                </div>
                <div class="module-r-fin-preview-grid">
                  <div class="module-r-fin-preview-title">X${i} GRID</div>
                  <svg class="module-r-fin-preview-svg" data-fin-preview="${i}" viewBox="0 0 240 130" preserveAspectRatio="xMidYMid meet">
                    <defs>
                      <pattern id="fin-grid-${i}" width="12" height="12" patternUnits="userSpaceOnUse">
                        <path d="M 12 0 L 0 0 0 12" fill="none" stroke="rgba(0,243,255,0.25)" stroke-width="1" />
                      </pattern>
                    </defs>
                    <rect x="0" y="0" width="240" height="130" fill="url(#fin-grid-${i})" />
                    <g transform="translate(0,0)">
                      <path data-shape="fin" d="M 14,116 L 120,116 L 96,42 L 46,42 Z" fill="rgba(0,243,255,0.28)" stroke="rgba(255,215,0,0.9)" stroke-width="2" />
                    </g>
                  </svg>
                </div>
              </div>
            `);
          }
          finsList.innerHTML = finRowsHtml.join("");
          for (let i = 1; i <= count; i += 1) {
            attachFinRowListeners(i);
          }
          showPage("fins-detail");
        });

        finsSaveBtn?.addEventListener("click", () => {
          if (!finsList) return;
          const finSetCount = Number(finsCountInput?.value);
          if (Number.isFinite(finSetCount) && finSetCount > 0) {
            const fins = Array.from({ length: finSetCount }, (_, idx) => {
              const index = idx + 1;
              const getSelect = (name: string) =>
                finsList.querySelector(`select[name="fin_${name}_${index}"]`) as
                  | HTMLSelectElement
                  | null;
              const getNumber = (name: string, fallback = 0) => {
                const input = finsList.querySelector(
                  `input[name="${name}_${index}"]`
                ) as HTMLInputElement | null;
                const value = Number(input?.value ?? fallback);
                return Number.isFinite(value) ? value : fallback;
              };
              const type = getSelect("type")?.value || "trapezoidal";
              const baseCount = Math.max(2, getNumber("fin_count", 3));
              let root = getNumber("fin_root", 2);
              let tip = getNumber("fin_tip", 2);
              let span = getNumber("fin_span", getNumber("fin_height", 1.2));
              let sweep = getNumber("fin_sweep", 0);
              const freePoints = [1, 2, 3, 4].map((n) => ({
                x: getNumber(`free_x_${n}`, n === 3 ? 3 : n === 4 ? 2 : n - 1),
                y: getNumber(`free_y_${n}`, n === 1 || n === 4 ? 0 : 2),
              }));
              const tubeOuter = getNumber("tube_outer_diameter", 2);
              const tubeAuto = Boolean(
                (
                  finsList.querySelector(`input[name="tube_auto_inner_${index}"]`) as
                    | HTMLInputElement
                    | null
                )?.checked
              );
              let tubeInner = getNumber("tube_inner_diameter", 1.8);
              if (tubeAuto && tubeOuter > 0) {
                tubeInner = Math.max(tubeOuter - 2 * Math.max(getNumber("fin_thickness", 0.08), 0.01), 0.02);
              }
              if (type === "elliptical") {
                root = getNumber("fin_root", 2);
                tip = root;
                span = getNumber("fin_height", 2);
                sweep = 0;
              } else if (type === "free_form") {
                const minX = Math.min(...freePoints.map((p) => p.x));
                const maxX = Math.max(...freePoints.map((p) => p.x));
                const minY = Math.min(...freePoints.map((p) => p.y));
                const maxY = Math.max(...freePoints.map((p) => p.y));
                root = Math.max(maxX - minX, 0.1);
                span = Math.max(maxY - minY, 0.1);
                tip = Math.max(freePoints[2].x - freePoints[1].x, 0.1);
                sweep = Math.max(freePoints[1].x - freePoints[0].x, 0);
              } else if (type === "tube_fin") {
                root = getNumber("tube_length", 4);
                tip = root;
                span = tubeOuter;
                sweep = 0;
              }
              const thickness = Math.max(0.01, getNumber("fin_thickness", 0.12));
              return {
                parent: getSelect("parent")?.value || "",
                type,
                count: baseCount,
                root,
                tip,
                span,
                sweep,
                thickness,
                material: getSelect("material")?.value || "Cardboard",
                finish: getSelect("finish")?.value || "regular_paint",
                cross_section: getSelect("cross_section")?.value || "square",
                position_relative: getSelect("position_relative")?.value || "bottom",
                plus_offset: getNumber("fin_plus_offset", 0),
                rotation_deg: getNumber("fin_rotation", 0),
                fillet_radius: getNumber("fin_fillet_radius", 0),
                fillet_material: getSelect("fillet_material")?.value || "Balsa",
                free_points: JSON.stringify(freePoints),
                tube_length: getNumber("tube_length", 4),
                tube_outer_diameter: tubeOuter,
                tube_inner_diameter: tubeInner,
                tube_auto_inner: tubeAuto,
              };
            });
            const hasInvalid = fins.some(
              (f: Record<string, unknown>) =>
                !Number.isFinite(Number(f.count)) ||
                Number(f.count) < 2 ||
                !Number.isFinite(Number(f.root)) ||
                Number(f.root) <= 0 ||
                !Number.isFinite(Number(f.span)) ||
                Number(f.span) <= 0 ||
                (String(f.type) === "tube_fin" &&
                  (!Number.isFinite(Number(f.tube_outer_diameter)) ||
                    Number(f.tube_outer_diameter) <= 0 ||
                    !Number.isFinite(Number(f.tube_inner_diameter)) ||
                    Number(f.tube_inner_diameter) < 0 ||
                    Number(f.tube_inner_diameter) >= Number(f.tube_outer_diameter))) ||
                (String(f.type) === "free_form" &&
                  (() => {
                    const raw = String(f.free_points || "[]");
                    try {
                      const pts = JSON.parse(raw) as Array<{ x?: number; y?: number }>;
                      if (!Array.isArray(pts) || pts.length < 3) return true;
                      let area = 0;
                      for (let i = 0; i < pts.length; i += 1) {
                        const p1 = pts[i];
                        const p2 = pts[(i + 1) % pts.length];
                        area += Number(p1.x ?? 0) * Number(p2.y ?? 0) - Number(p2.x ?? 0) * Number(p1.y ?? 0);
                      }
                      return Math.abs(area) < 0.001;
                    } catch {
                      return true;
                    }
                  })())
            );
            if (hasInvalid) {
              setStatus("COMPLETE ALL REQUIRED FIN SET FIELDS.");
              return;
            }
            window.localStorage.setItem("arx_module_r_fins", JSON.stringify(fins));
            window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          }
          window.localStorage.setItem("arx_module_r_fins_done", "true");
          if (Number.isFinite(finSetCount)) {
            window.localStorage.setItem("arx_module_r_fin_set_count", String(finSetCount));
          }
          updateCardStates();
          window.alert("Fin Sets saved.");
          showPage("manual");
          setStatus("FIN SETS SAVED.");
        });

        finsClearIndex?.addEventListener("click", () => {
          if (finsCountInput) finsCountInput.value = "";
          if (finsList) finsList.innerHTML = "";
          window.localStorage.setItem("arx_module_r_fins_done", "false");
          window.localStorage.removeItem("arx_module_r_fin_set_count");
          window.localStorage.removeItem("arx_module_r_fins");
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("FIN SETS CLEARED.");
        });

        finsClearBtn?.addEventListener("click", () => {
          if (finsCountInput) finsCountInput.value = "";
          if (finsList) finsList.innerHTML = "";
          window.localStorage.setItem("arx_module_r_fins_done", "false");
          window.localStorage.removeItem("arx_module_r_fin_set_count");
          window.localStorage.removeItem("arx_module_r_fins");
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          showPage("fins");
          setStatus("FIN SETS CLEARED.");
        });

        backFinsBtn?.addEventListener("click", () => {
          showPage("fins");
          setStatus("");
        });

        markBodyBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_body_motor_done", "true");
          window.localStorage.setItem("arx_module_r_body_additional_done", "true");
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "true");
          updateCardStates();
          showPage("manual");
        });
        unmarkBodyBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_body_motor_done", "false");
          window.localStorage.setItem("arx_module_r_body_additional_done", "false");
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "false");
          updateCardStates();
        });
        clearBodyBtn?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_module_r_motor_owned");
          window.localStorage.removeItem("arx_module_r_additional_owned");
          window.localStorage.removeItem("arx_module_r_bulkheads_owned");
          window.localStorage.setItem("arx_module_r_body_motor_done", "false");
          window.localStorage.setItem("arx_module_r_body_additional_done", "false");
          window.localStorage.setItem("arx_module_r_body_bulkheads_done", "false");
          window.localStorage.removeItem("arx_module_r_stage_count");
          window.localStorage.removeItem("arx_module_r_additional_count");
          window.localStorage.removeItem("arx_module_r_bulkhead_count");
          window.localStorage.removeItem("arx_module_r_motor_mounts");
          window.localStorage.removeItem("arx_module_r_additional_tubes");
          window.localStorage.removeItem("arx_module_r_bulkheads");
          if (stageCountInput) stageCountInput.value = "";
          if (stageList) stageList.innerHTML = "";
          if (additionalCountInput) additionalCountInput.value = "";
          if (additionalList) additionalList.innerHTML = "";
          if (bulkheadCountInput) bulkheadCountInput.value = "";
          if (bulkheadList) bulkheadList.innerHTML = "";
          window.dispatchEvent(new Event("arx:module-r:parts-updated"));
          updateCardStates();
          setStatus("BODY TUBES CLEARED.");
        });
        markNoseBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_nose_done", "true");
          updateCardStates();
          showPage("manual");
        });
        unmarkNoseBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_nose_done", "false");
          updateCardStates();
        });
        markFinsBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_fins_done", "true");
          updateCardStates();
          showPage("manual");
        });
        unmarkFinsBtn?.addEventListener("click", () => {
          window.localStorage.setItem("arx_module_r_fins_done", "false");
          updateCardStates();
        });

        submitAuto?.addEventListener("click", async () => {
          const fileInput = ricInput;
          const lengthInput = moduleR.querySelector('input[name="upper_length_m"]') as
            | HTMLInputElement
            | null;
          const massInput = moduleR.querySelector('input[name="upper_mass_kg"]') as
            | HTMLInputElement
            | null;
          const apogeeInput = moduleR.querySelector('input[name="target_apogee_m"]') as
            | HTMLInputElement
            | null;
          const includeBallast = moduleR.querySelector('input[name="include_ballast"]') as
            | HTMLInputElement
            | null;
          const includeTelemetry = moduleR.querySelector('input[name="include_telemetry"]') as
            | HTMLInputElement
            | null;
          const includeParachute = moduleR.querySelector('input[name="include_parachute"]') as
            | HTMLInputElement
            | null;
          const topNInput = moduleR.querySelector('input[name="top_n"]') as
            | HTMLInputElement
            | null;
          const seedInput = moduleR.querySelector('input[name="random_seed"]') as
            | HTMLInputElement
            | null;

          if (!fileInput?.files || fileInput.files.length === 0) {
            setStatus("UPLOAD A .RIC FILE.");
            return;
          }
          const upperLengthIn = Number(lengthInput?.value);
          const upperMassLb = Number(massInput?.value);
          if (!Number.isFinite(upperLengthIn) || upperLengthIn <= 0) {
            setStatus("ENTER UPPER LENGTH.");
            return;
          }
          if (!Number.isFinite(upperMassLb) || upperMassLb <= 0) {
            setStatus("ENTER UPPER MASS.");
            return;
          }
          const targetApogeeFt = Number(apogeeInput?.value);
          const upperLength = upperLengthIn * 0.0254;
          const upperMass = upperMassLb * 0.45359237;
          const targetApogee = Number.isFinite(targetApogeeFt) ? targetApogeeFt * 0.3048 : NaN;

          const payload = new FormData();
          Array.from(fileInput.files).forEach((file) => {
            payload.append("ric_file", file);
          });
          const stageCount = window.localStorage.getItem("arx_module_r_stage_count");
          if (stageCount) {
            payload.append("stage_count", stageCount);
          }
          payload.append("upper_length_m", String(upperLength));
          payload.append("upper_mass_kg", String(upperMass));
          if (Number.isFinite(targetApogee) && targetApogee > 0) {
            payload.append("target_apogee_m", String(targetApogee));
          }
          payload.append("include_ballast", includeBallast?.checked ? "true" : "false");
          payload.append("include_telemetry", includeTelemetry?.checked ? "true" : "false");
          payload.append("include_parachute", includeParachute?.checked ? "true" : "false");
          const topN = Number(topNInput?.value || 5);
          if (Number.isFinite(topN) && topN > 0) payload.append("top_n", String(Math.floor(topN)));
          const randomSeed = Number(seedInput?.value);
          if (Number.isFinite(randomSeed)) payload.append("random_seed", String(Math.floor(randomSeed)));
          window.localStorage.setItem(
            "arx_module_r_auto_prefs",
            JSON.stringify({
              upper_length_in: upperLengthIn,
              upper_mass_lb: upperMassLb,
              target_apogee_ft: Number.isFinite(targetApogeeFt) ? targetApogeeFt : null,
              include_ballast: Boolean(includeBallast?.checked),
              include_telemetry: Boolean(includeTelemetry?.checked),
              include_parachute: Boolean(includeParachute?.checked),
              top_n: Number.isFinite(topN) ? Math.floor(topN) : 5,
              random_seed: Number.isFinite(randomSeed) ? Math.floor(randomSeed) : null,
            })
          );
          if (autoResultsEl) autoResultsEl.innerHTML = "";

          const buildDownloadUrl = (orkPath?: string) => {
            if (!orkPath) return "";
            if (orkPath.startsWith("http")) return orkPath;
            const normalized = orkPath.replace(/\\/g, "/");
            const testsMarker = "/tests/";
            const relative = normalized.includes(testsMarker)
              ? normalized.split(testsMarker)[1]
              : normalized.split("/").slice(-2).join("/");
            if (!relative) return "";
            const encoded = relative
              .split("/")
              .filter(Boolean)
              .map((segment) => encodeURIComponent(segment))
              .join("/");
            return `${API_BASE}/api/v1/downloads/${encoded}`;
          };

          let progress = 5;
          const progressStages = [
            "Parsing motor file(s)",
            "Loading component library",
            "Generating candidates",
            "Filtering invalid rockets",
            "Scoring and ranking",
            "Selecting winner and exporting .ork",
          ];
          let progressStageIndex = 0;
          setStatus(
            `AUTO-BUILD IN PROGRESS... ${progress}% | ${progressStages[progressStageIndex]}`
          );
          const progressTimer = window.setInterval(() => {
            progress = Math.min(progress + 7, 90);
            if (progress >= 20 && progressStageIndex < progressStages.length - 1) {
              progressStageIndex = Math.min(
                progressStages.length - 1,
                Math.floor((progress / 100) * progressStages.length)
              );
            }
            setStatus(
              `AUTO-BUILD IN PROGRESS... ${progress}% | ${progressStages[progressStageIndex]}`
            );
          }, 450);

          try {
            const response = await fetch(`${API_BASE}/api/v1/module-r/auto-build/upload`, {
              method: "POST",
              body: payload,
            });
            window.clearInterval(progressTimer);
            if (!response.ok) {
              let detail = "";
              try {
                const errorJson = await response.json();
                detail = String(errorJson?.detail || "");
              } catch {
                detail = await response.text();
              }
              const lowerDetail = (detail || "").toLowerCase();
              let friendly = detail || "UNKNOWN ERROR";
              if (lowerDetail.includes("no physically valid candidates")) {
                friendly =
                  "No valid rocket matched your limits. Try increasing max length/mass, lowering target apogee, or enabling telemetry/parachute.";
              } else if (lowerDetail.includes("exceeds feasible length budget")) {
                friendly = toImperialAutoBuildError(detail);
              } else if (lowerDetail.includes("no compatible body tubes")) {
                friendly =
                  "No compatible body tube found for this motor. Try another .ric or broaden constraints.";
              } else if (
                lowerDetail.includes("motor fit") ||
                lowerDetail.includes("motor_mount") ||
                lowerDetail.includes("motor mount")
              ) {
                friendly =
                  "Motor mount fit failed. Check stage count or try a different motor geometry.";
              } else if (
                lowerDetail.includes("ric") ||
                lowerDetail.includes("grain") ||
                lowerDetail.includes("invalid motor")
              ) {
                friendly = "RIC parsing failed. Verify the uploaded motor file is valid and complete.";
              } else {
                friendly = toImperialAutoBuildError(friendly);
              }
              setStatus(`AUTO-BUILD FAILED: ${friendly}`);
              return;
            }
            const result = await response.json();
            renderAutoBuildResults(result);
            if (result?.assembly) {
              window.localStorage.setItem(
                "arx_module_r_latest_auto_assembly",
                JSON.stringify(result.assembly)
              );
              window.dispatchEvent(new Event("arx:module-r:parts-updated"));
            }
            if (result?.ork_path) {
              window.localStorage.setItem("arx_module_r_ork_path", result.ork_path);
              const downloadUrl = buildDownloadUrl(result.ork_path);
              if (downloadUrl) {
                window.open(downloadUrl, "_blank", "noopener,noreferrer");
              }
            }
            const variant = String(
              (result as { assembly?: { metadata?: { backend_variant?: unknown } } } | undefined)?.assembly
                ?.metadata?.backend_variant ?? "unknown"
            );
            setStatus(`AUTO-BUILD COMPLETE. 100% | backend=${variant}`);
          } catch (error) {
            window.clearInterval(progressTimer);
            console.error(error);
            setStatus("AUTO-BUILD ERROR.");
          }
        });
      }
      let pendingSuccessToken = Date.now();
      const cancelPendingSuccess = () => {
        pendingSuccessToken = Date.now();
      };
      const showSuccessLayer = (
        message: string,
        holdMs: number,
        onComplete?: () => void
      ) => {
        const successLayer = document.getElementById("success-layer");
        if (!successLayer) return;
        successLayer.innerHTML = `<div class="form-success">${message}</div>`;
        const success = successLayer.querySelector(".form-success") as HTMLElement | null;
        if (!success) return;
        requestAnimationFrame(() => success.classList.add("visible"));
        const token = pendingSuccessToken;
        setTimeout(() => {
          if (pendingSuccessToken !== token) return;
          success.classList.add("fade-out");
          setTimeout(() => {
            if (pendingSuccessToken !== token) return;
            successLayer.innerHTML = "";
            onComplete?.();
          }, 1500);
        }, holdMs);
      };
      const readDobValue = () => {
        if (!form) return "";
        const monthInput = form.querySelector(
          'input[name="dob_month"]'
        ) as HTMLInputElement | null;
        const dayInput = form.querySelector(
          'input[name="dob_day"]'
        ) as HTMLInputElement | null;
        const yearInput = form.querySelector(
          'input[name="dob_year"]'
        ) as HTMLInputElement | null;
        if (!monthInput || !dayInput || !yearInput) {
          const fields = new FormData(form);
          return String(fields.get("dob") || "").trim();
        }
        const month = monthInput.value.trim();
        const day = dayInput.value.trim();
        const year = yearInput.value.trim();
        if (!month && !day && !year) return "";
        if (month.length < 2 || day.length < 2 || year.length < 4) return "";
        const parsedDob = parseDobParts(month, day, year);
        if (!parsedDob.valid || !parsedDob.date) return "";
        return `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(
          2,
          "0"
        )}`;
      };

      const handleSubmit = () => {
        const status = container.querySelector(".form-status") as HTMLElement | null;
        const formType = form?.getAttribute("data-form");
        const fields = form ? new FormData(form) : null;
        if (!fields) return;
        if (formType === "login") {
          const email = String(fields.get("email") || "").trim();
          const password = String(fields.get("password") || "").trim();
          if (!email || !password) {
            if (status) status.textContent = "ENTER EMAIL AND ACCESS CODE.";
            return;
          }
          pendingSubPageType = null;
          showSuccessLayer("YOU HAVE BEEN LOGGED IN SUCCESSFULLY.", 6000);
        loggedInEmail = email;
        updateAuthUI();
          const loginLayer = document.getElementById("login-layer");
          if (loginLayer) loginLayer.innerHTML = "";
          const floater = document.getElementById("activeFloater");
          if (floater) floater.remove();
          const titleEl = document.getElementById("activeModuleTitle");
          if (titleEl) titleEl.remove();
          document.getElementById("arc-reactor-overlay")?.classList.remove("active");
          document
            .getElementById("arc-reactor-overlay")
            ?.classList.remove("form-mode");
          setTimeout(() => {
          resetDashboard();
        }, 7500);
        } else if (formType === "new") {
          const name = String(fields.get("name") || "").trim();
          const email = String(fields.get("email") || "").trim();
          const password = String(fields.get("password") || "").trim();
          const dob = readDobValue();
          if (!dob) {
            if (status) status.textContent = "PLEASE PUT REAL DATE.";
            return;
          }
          if (!name || !email || !password) {
            if (status) status.textContent = "INPUT INFORMATION.";
            return;
          }
          const formEl = container.querySelector("form");
          formEl?.classList.add("fade-out");
          const floater = document.getElementById("activeFloater");
          if (floater) floater.remove();
          const titleEl = document.getElementById("activeModuleTitle");
          if (titleEl) titleEl.remove();
          const overlay = document.getElementById("arc-reactor-overlay");
          overlay?.classList.remove("active");
          overlay?.classList.remove("form-mode");
          setTimeout(() => {
            const onFadeEnd = () => {
              overlay?.removeEventListener("transitionend", onFadeEnd);
              showSuccessLayer("WELCOME. YOU HAVE BEEN REGISTERED TO A.R.X.", 5000, () => {
                showSuccessLayer("YOU CAN GO TO LOGIN NOW.", 4000, () => {
                  resetDashboard();
                });
              });
            };
            if (overlay) {
              overlay.addEventListener("transitionend", onFadeEnd, { once: true });
            } else {
              showSuccessLayer("WELCOME. YOU HAVE BEEN REGISTERED TO A.R.X.", 5000, () => {
                showSuccessLayer("YOU CAN GO TO LOGIN NOW.", 4000);
              });
            }
            const loginLayer = document.getElementById("login-layer");
            if (loginLayer) {
              setTimeout(() => {
                loginLayer.innerHTML = "";
              }, 3000);
            }
          }, 1200);
        } else if (formType === "proto") {
          const name = String(fields.get("name") || "").trim();
          const email = String(fields.get("email") || "").trim();
          const message = String(fields.get("message") || "").trim();
          if (!name || !email || !message) {
            if (status) status.textContent = "NOTHING TO TRANSMIT.";
            return;
          }
          const formEl = container.querySelector("form");
          formEl?.classList.add("fade-out");
          const floater = document.getElementById("activeFloater");
          if (floater) floater.remove();
          const titleEl = document.getElementById("activeModuleTitle");
          if (titleEl) titleEl.remove();
          const overlay = document.getElementById("arc-reactor-overlay");
          overlay?.classList.remove("active");
          overlay?.classList.remove("form-mode");
          setTimeout(() => {
            const onFadeEnd = () => {
              overlay?.removeEventListener("transitionend", onFadeEnd);
              showSuccessLayer(
                "YOUR MISSION BRIEF HAS BEEN SENT TO THE CREATORS.",
                5000,
                () => {
                  const loginLayer = document.getElementById("login-layer");
                  if (loginLayer) {
                    loginLayer.innerHTML = `
                      <form class="subpage-form login-layer-form" data-form="proto" novalidate>
                        <div class="form-title">PROTOCOL 8</div>
                        <div class="form-subtitle">SECURE CONTACT CHANNEL</div>
                        <div class="arx-field">
                          <input type="text" name="name" placeholder=" " autocomplete="name" required />
                          <label>YOUR NAME</label>
                        </div>
                        <div class="arx-field">
                          <input type="email" name="email" placeholder=" " autocomplete="email" required />
                          <label>YOUR EMAIL</label>
                        </div>
                        <div class="arx-field">
                          <textarea name="message" placeholder=" " required></textarea>
                          <label>MISSION BRIEF</label>
                        </div>
                        <div class="form-status"></div>
                        <div class="arx-form-actions">
                          <button type="submit" class="arx-btn">Transmit</button>
                          <button type="button" class="arx-btn" id="proto-clear">Clear</button>
                        </div>
                      </form>
                    `;
                    bindFormActions(loginLayer);
                  }
                }
              );
            };
            if (overlay) {
              overlay.addEventListener("transitionend", onFadeEnd, { once: true });
            } else {
              showSuccessLayer("YOUR MISSION BRIEF HAS BEEN SENT TO THE CREATORS.", 5000);
            }
            const loginLayer = document.getElementById("login-layer");
            if (loginLayer) {
              setTimeout(() => {
                loginLayer.innerHTML = "";
              }, 3000);
            }
          }, 1200);
        }
      };

      const hasAnyDobInput = () => {
        if (!form) return false;
        const monthInput = form.querySelector(
          'input[name="dob_month"]'
        ) as HTMLInputElement | null;
        const dayInput = form.querySelector(
          'input[name="dob_day"]'
        ) as HTMLInputElement | null;
        const yearInput = form.querySelector(
          'input[name="dob_year"]'
        ) as HTMLInputElement | null;
        if (!monthInput || !dayInput || !yearInput) {
          const fields = new FormData(form);
          return Boolean(String(fields.get("dob") || "").trim());
        }
        return Boolean(
          monthInput.value.trim() || dayInput.value.trim() || yearInput.value.trim()
        );
      };

      const handleClear = () => {
        const status = container.querySelector(".form-status") as HTMLElement | null;
        const fields = form ? new FormData(form) : null;
        const formType = form?.getAttribute("data-form");
        if (formType === "login" && fields) {
          const email = String(fields.get("email") || "").trim();
          const password = String(fields.get("password") || "").trim();
          if (!email && !password) {
            if (status) status.textContent = "NOTHING TO CLEAR.";
            return;
          }
        } else if (formType === "new" && fields) {
          const name = String(fields.get("name") || "").trim();
          const email = String(fields.get("email") || "").trim();
          const password = String(fields.get("password") || "").trim();
          const hasDob = hasAnyDobInput();
          if (!name && !email && !password && !hasDob) {
            if (status) status.textContent = "NOTHING TO RESET.";
            return;
          }
        } else if (formType === "proto" && fields) {
          const name = String(fields.get("name") || "").trim();
          const email = String(fields.get("email") || "").trim();
          const message = String(fields.get("message") || "").trim();
          if (!name && !email && !message) {
            if (status) status.textContent = "NOTHING TO CLEAR.";
            return;
          }
        }
        form?.querySelectorAll("input, textarea").forEach((field) => {
          (field as HTMLInputElement | HTMLTextAreaElement).value = "";
        });
        container.querySelectorAll(".dob-field").forEach((field) => {
          field.classList.remove("is-active");
          field.classList.remove("age-active");
          const label = field.querySelector("label");
          if (label) label.textContent = "DATE OF BIRTH";
          const age = field.querySelector(".dob-age");
          if (age) age.textContent = "";
        });
        if (status) status.textContent = "";
      };

      form?.addEventListener("submit", (event) => {
        event.preventDefault();
        handleSubmit();
      });
      const clearBtn = container.querySelector("#login-clear, #newuser-clear, #proto-clear");
      clearBtn?.addEventListener("click", () => {
        handleClear();
      });
      const hoverButtons = container.querySelectorAll(".arx-btn");
      hoverButtons.forEach((button) => {
        button.addEventListener("mouseenter", () => {
          const sound = floatSound.cloneNode() as HTMLAudioElement;
          sound.volume = 0.5;
          sound.play().catch(() => {});
        });
      });

      const resetButton = document.getElementById("subPageBtn");
      resetButton?.addEventListener("click", () => {
        cancelPendingSuccess();
      });
    };

    const awaitSubPageKey = (type: string) => {
      pendingSubPageType = type === "SYSTEM" ? "A_PRECHECK" : type;
      isSubPageLocked = false;
      document.getElementById("subPage")?.classList.remove("locked");
      showPressAnyKeyHint();
    };

    const showPressAnyKeyHint = () => {
      const hint = document.getElementById("spacebar-hint");
      if (hint) {
        hint.textContent = "PRESS ANY KEY TO CONTINUE";
        hint.classList.remove("visible");
        requestAnimationFrame(() => hint.classList.add("visible"));
      }
    };

    const unlockSubPage = () => {
      isSubPageLocked = false;
      pendingSubPageType = null;
      document.getElementById("subPage")?.classList.remove("locked");
      const subPageContent = document.getElementById("subPageContent") as HTMLElement | null;
      if (subPageContent) {
        subPageContent.style.pointerEvents = "auto";
      }
      const hint = document.getElementById("spacebar-hint");
      if (hint) {
        hint.classList.remove("visible");
        hint.textContent = "PRESS SPACEBAR TO INITIALIZE";
      }
      const floater = document.getElementById("activeFloater");
      if (floater && floater.classList.contains("centered-contained-word")) {
        floater.remove();
      }
      const titleEl = document.getElementById("activeModuleTitle");
      if (titleEl) {
        titleEl.remove();
      }
    };

    const revealPendingSubPage = () => {
      const type = pendingSubPageType;
      if (!type) return;
      const floater = document.getElementById("activeFloater");
      if (floater && floater.classList.contains("centered-contained-word")) {
        floater.remove();
      }
      const titleEl = document.getElementById("activeModuleTitle");
      if (titleEl) {
        titleEl.remove();
      }
      const subPageContent = document.getElementById("subPageContent");
      if (!subPageContent) return;
      if (type === "INIT") {
        subPageContent.innerHTML = `
          <form class="subpage-form" data-form="login" novalidate>
            <div class="form-title">LOGIN ACCESS</div>
            <div class="form-subtitle">SECURE AUTHENTICATION REQUIRED</div>
            <div class="arx-field">
              <input type="email" name="email" placeholder=" " autocomplete="email" required />
              <label>YOUR EMAIL</label>
            </div>
            <div class="arx-field">
              <input type="password" name="password" placeholder=" " autocomplete="current-password" required />
              <label>ACCESS CODE</label>
            </div>
            <div class="form-status"></div>
            <div class="arx-form-actions">
              <button type="submit" class="arx-btn">Authorize</button>
              <button type="button" class="arx-btn" id="login-clear">Clear</button>
            </div>
          </form>
        `;
      } else if (type === "NEW") {
        subPageContent.innerHTML = `
          <form class="subpage-form" data-form="new" novalidate>
            <div class="form-title">NEW USER</div>
            <div class="form-subtitle">REGISTER ARX ACCESS</div>
            <div class="arx-field">
              <input type="text" name="name" placeholder=" " autocomplete="name" required />
              <label>YOUR NAME</label>
            </div>
            <div class="arx-field">
              <input type="email" name="email" placeholder=" " autocomplete="email" required />
              <label>YOUR EMAIL</label>
            </div>
            <div class="arx-field">
              <input
                type="password"
                name="password"
                placeholder=" "
                autocomplete="new-password"
                required
              />
              <label>YOUR PASSWORD</label>
            </div>
            <div class="arx-field dob-field">
              <div class="dob-inputs">
                <input
                  type="text"
                  name="dob_month"
                  inputmode="numeric"
                  pattern="[0-9]*"
                  maxlength="2"
                  placeholder="MM"
                  autocomplete="bday-month"
                  required
                />
                <span class="dob-sep">/</span>
                <input
                  type="text"
                  name="dob_day"
                  inputmode="numeric"
                  pattern="[0-9]*"
                  maxlength="2"
                  placeholder="DD"
                  autocomplete="bday-day"
                  required
                />
                <span class="dob-sep">/</span>
                <input
                  type="text"
                  name="dob_year"
                  inputmode="numeric"
                  pattern="[0-9]*"
                  maxlength="4"
                  placeholder="YYYY"
                  autocomplete="bday-year"
                  required
                />
                <button
                  type="button"
                  class="dob-calendar-btn"
                  aria-label="Open calendar"
                ></button>
              </div>
              <label>DATE OF BIRTH</label>
              <div class="dob-age" aria-live="polite"></div>
            </div>
            <div class="form-status"></div>
            <div class="arx-form-actions">
              <button type="submit" class="arx-btn">Register</button>
              <button type="button" class="arx-btn" id="newuser-clear">Reset</button>
            </div>
          </form>
        `;
      } else if (type === "A_PRECHECK") {
        document.body.classList.add("grid-only");
        document.body.classList.add("panel-active");
        document.body.classList.remove("holo-active");
        subPageContent.innerHTML = `
          <div class="subpage-form" data-form="ork-precheck">
            <div class="form-title">UPLOAD ORK?</div>
            <div class="form-subtitle">DO YOU WANT TO UPLOAD AN ORK FILE?</div>
            <div class="arx-field">
              <a class="link-button" id="ork-upload-link" href="#">upload .ork</a>
              <input id="ork-upload-input" type="file" accept=".ork" hidden />
            </div>
            <div class="arx-field">
              <a class="link-button" id="cdx-upload-link" href="#">upload .cdx1 (optional)</a>
              <input id="cdx-upload-input" type="file" accept=".cdx1" hidden />
            </div>
            <div class="field-hint">
              If you just want to make a motor and use the A module we need you to upload an .ork file for the most accurate results.
            </div>
            <div class="form-status" id="ork-upload-status"></div>
            <div class="arx-form-actions">
              <button type="button" class="arx-btn" id="ork-no-btn">No</button>
              <button type="button" class="arx-btn" id="ork-continue-btn" disabled>Continue</button>
            </div>
          </div>
        `;

        const uploadLink = subPageContent.querySelector("#ork-upload-link") as HTMLAnchorElement | null;
        const uploadInput = subPageContent.querySelector("#ork-upload-input") as HTMLInputElement | null;
        const cdxUploadLink = subPageContent.querySelector("#cdx-upload-link") as HTMLAnchorElement | null;
        const cdxUploadInput = subPageContent.querySelector("#cdx-upload-input") as HTMLInputElement | null;
        const status = subPageContent.querySelector("#ork-upload-status") as HTMLElement | null;
        const noBtn = subPageContent.querySelector("#ork-no-btn") as HTMLButtonElement | null;
        const continueBtn = subPageContent.querySelector("#ork-continue-btn") as HTMLButtonElement | null;

        const parseOrkFile = async (file: File) => {
          const readOrkXmlText = async (input: File) => {
            const buffer = await input.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            const isZip = bytes.length >= 2 && bytes[0] === 0x50 && bytes[1] === 0x4b;
            if (isZip) {
              const zip = await JSZip.loadAsync(buffer);
              const xmlName = Object.keys(zip.files).find(
                (name) => name.endsWith(".ork") || name.endsWith(".xml")
              );
              if (!xmlName) {
                throw new Error("ORK archive missing .ork XML");
              }
              return zip.files[xmlName].async("text");
            }
            return new TextDecoder().decode(buffer);
          };

          const parseLength = (node: Element, tag: string) => {
            for (const child of Array.from(node.children)) {
              if (child.tagName.toLowerCase() === tag) {
                const value = Number(child.textContent ?? "");
                return Number.isFinite(value) ? value : 0;
              }
            }
            return 0;
          };

          const calculateStackLength = (rootXml: Document) => {
            let totalStackLength = 0;
            const stages = Array.from(rootXml.querySelectorAll("stage"));
            for (const stage of stages) {
              const stageSubcomponents = stage.querySelector("subcomponents");
              if (!stageSubcomponents) continue;
              let stageLen = 0;
              for (const component of Array.from(stageSubcomponents.children)) {
                const tag = component.tagName.toLowerCase();
                if (["nosecone", "bodytube", "transition"].includes(tag)) {
                  const rawLen =
                    parseLength(component, "length") || parseLength(component, "len");
                  let shoulderDeduction = 0;
                  for (const child of Array.from(component.children)) {
                    if (child.tagName.toLowerCase().includes("shoulder")) {
                      shoulderDeduction =
                        parseLength(child, "length") || parseLength(child, "len");
                    }
                  }
                  const exposedLen = Math.max(0, rawLen - shoulderDeduction);
                  stageLen += exposedLen;
                }
              }
              totalStackLength += stageLen;
            }
            return totalStackLength;
          };

          const text = await readOrkXmlText(file);
          const parser = new DOMParser();
          const doc = parser.parseFromString(text, "application/xml");
          const rocket = doc.querySelector("rocket");
          if (!rocket) {
            throw new Error("Invalid ORK file");
          }
          const rocketLengthM = calculateStackLength(doc);

          let maxRadius = 0;
          doc.querySelectorAll("nosecone, bodytube, transition").forEach((node) => {
            ["radius", "outerradius", "aftradius"].forEach((tag) => {
              const radius = node.querySelector(tag);
              if (radius?.textContent) {
                const value = Number(radius.textContent);
                if (Number.isFinite(value)) maxRadius = Math.max(maxRadius, value);
              }
            });
          });
          const diameterM = maxRadius > 0 ? maxRadius * 2 : 0;

          const getMassFromSimulation = (rootXml: Document) => {
            const flightData = rootXml.querySelector("flightdata");
            if (!flightData) return 0;
            const branch = flightData.querySelector("databranch");
            if (!branch) return 0;
            const types = (branch.getAttribute("types") || "")
              .split(",")
              .map((value) => value.trim());
            const massIndex = types.indexOf("Mass");
            const motorIndex = types.indexOf("Motor mass");
            if (massIndex === -1 || motorIndex === -1) return 0;
            const firstPoint = branch.querySelector("datapoint");
            if (!firstPoint?.textContent) return 0;
            const values = firstPoint.textContent.trim().split(",");
            if (values.length <= Math.max(massIndex, motorIndex)) return 0;
            const totalMassKg = Number(values[massIndex]);
            const motorMassKg = Number(values[motorIndex]);
            if (!Number.isFinite(totalMassKg) || !Number.isFinite(motorMassKg)) return 0;
            const dryMassKg = totalMassKg - motorMassKg;
            return Number.isFinite(dryMassKg) ? totalMassKg : 0;
          };

          const massKg = getMassFromSimulation(doc);

          const toInches = (meters: number) => meters * 39.3701;
          const toPounds = (kg: number) => kg * 2.20462;

          return {
            rocket_length_in: toInches(rocketLengthM),
            ref_diameter_in: toInches(diameterM),
            total_mass_lb: toPounds(massKg),
            file_name: file.name,
          };
        };
        const parseCdxFile = async (file: File) => {
          const text = await file.text();
          const parser = new DOMParser();
          const doc = parser.parseFromString(text, "application/xml");
          const launchSite = doc.querySelector("LaunchSite");
          const simulation = doc.querySelector("SimulationList > Simulation");
          const altitude = launchSite?.querySelector("Altitude")?.textContent;
          const rodLength = launchSite?.querySelector("RodLength")?.textContent;
          const temperature = launchSite?.querySelector("Temperature")?.textContent;
          const windSpeed = launchSite?.querySelector("WindSpeed")?.textContent;
          const rodAngle = launchSite?.querySelector("RodAngle")?.textContent;
          const sustainerIgnition = simulation?.querySelector("SustainerIgnitionDelay")?.textContent;
          const boosterSeparation = simulation?.querySelector("Booster1SeparationDelay")?.textContent;
          const boosterIgnition = simulation?.querySelector("Booster1IgnitionDelay")?.textContent;
          return {
            altitude_ft: Number(altitude),
            rod_length_ft: Number(rodLength),
            temperature_f: Number(temperature),
            wind_speed: Number(windSpeed),
            launch_angle_deg: Number(rodAngle),
            sustainer_ignition_s: Number(sustainerIgnition),
            booster_separation_s: Number(boosterSeparation),
            booster_ignition_s: Number(boosterIgnition),
            file_name: file.name,
          };
        };

        uploadLink?.addEventListener("click", (event) => {
          event.preventDefault();
          uploadInput?.click();
        });
        uploadInput?.addEventListener("change", async () => {
          const file = uploadInput.files?.[0];
          if (!file) return;
          try {
            const profile = await parseOrkFile(file);
            window.localStorage.setItem("arx_use_ork", "true");
            window.localStorage.setItem("arx_ork_vehicle_profile", JSON.stringify(profile));
            try {
              const form = new FormData();
              form.append("file", file, file.name);
              const response = await fetch(`${API_BASE}/api/v1/ork/upload`, {
                method: "POST",
                body: form,
              });
              if (!response.ok) {
                const detail = await response.text();
                throw new Error(detail || "ORK upload failed");
              }
              const payload = (await response.json()) as { path?: string };
              if (payload?.path) {
                window.localStorage.setItem("arx_ork_path", payload.path);
                try {
                  const parseResponse = await fetch(`${API_BASE}/api/v1/ork/parse`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: payload.path }),
                  });
                  if (parseResponse.ok) {
                    const parsed = (await parseResponse.json()) as {
                      assembly?: unknown;
                      warnings?: string[];
                    };
                    if (parsed?.assembly) {
                      window.localStorage.setItem(
                        "arx_module_r_latest_auto_assembly",
                        JSON.stringify(parsed.assembly)
                      );
                      window.dispatchEvent(new Event("arx:module-r:parts-updated"));
                    }
                    if (Array.isArray(parsed?.warnings) && parsed.warnings.length > 0) {
                      console.warn("ORK parse warnings:", parsed.warnings);
                    }
                  }
                } catch (parseError) {
                  console.warn("ORK parse bridge failed", parseError);
                }
              }
            } catch (error) {
              console.warn("ORK upload failed", error);
            }
            if (status) status.textContent = `Loaded ${profile.file_name}`;
            if (continueBtn) continueBtn.disabled = false;
          } catch (error) {
            console.error(error);
            if (status) status.textContent = "Failed to read ORK file.";
          }
        });
        cdxUploadLink?.addEventListener("click", (event) => {
          event.preventDefault();
          cdxUploadInput?.click();
        });
        cdxUploadInput?.addEventListener("change", async () => {
          const file = cdxUploadInput.files?.[0];
          if (!file) return;
          try {
            const profile = await parseCdxFile(file);
            window.localStorage.setItem("arx_cdx1_profile", JSON.stringify(profile));
            if (status) status.textContent = `Loaded ${profile.file_name}`;
          } catch (error) {
            console.error(error);
            if (status) status.textContent = "Failed to read CDX1 file.";
          }
        });
        noBtn?.addEventListener("click", () => {
          window.localStorage.removeItem("arx_use_ork");
          window.localStorage.removeItem("arx_ork_vehicle_profile");
          window.localStorage.removeItem("arx_cdx1_profile");
          window.localStorage.removeItem("arx_ork_path");
          pendingSubPageType = "SYSTEM";
          revealPendingSubPage();
        });
        continueBtn?.addEventListener("click", () => {
          pendingSubPageType = "SYSTEM";
          revealPendingSubPage();
        });
      } else if (type === "RESULTS") {
        const stored = window.localStorage.getItem("arx_mission_target_result");
        let result: Record<string, unknown> | null = null;
        if (stored) {
          try {
            result = JSON.parse(stored) as Record<string, unknown>;
          } catch (error) {
            console.warn("Invalid arx_mission_target_result JSON", error);
          }
        }
        const storedCandidate = (result?.candidate as Record<string, unknown> | undefined) || undefined;
        const jobResult = (result?.job as { result?: Record<string, unknown> } | undefined)?.result;
        const jobMotorlib = (jobResult?.openmotor_motorlib_result as Record<string, unknown> | undefined) || undefined;
        const jobCandidates = (jobMotorlib?.candidates as Record<string, unknown>[] | undefined) || [];
        const jobRanked = (jobMotorlib?.ranked as Record<string, unknown>[] | undefined) || [];
        const jobCandidate = jobRanked[0] || jobCandidates[0];
        const candidate = jobCandidate || (jobResult ? undefined : storedCandidate);
        const artifacts = (candidate?.artifacts as Record<string, string> | undefined) || undefined;
        const metrics = (candidate?.metrics as Record<string, unknown> | undefined) || {};
        const stageMetrics = (candidate?.stage_metrics as Record<string, unknown> | undefined) || {};
        const estimatedTotalImpulse = Number(
          (jobResult as { estimated_total_impulse_ns?: number } | undefined)?.estimated_total_impulse_ns ??
            (candidate as { estimated_total_impulse_ns?: number } | undefined)?.estimated_total_impulse_ns
        );
        const withinTolerance = Boolean(
          (candidate as { within_tolerance?: boolean } | undefined)?.within_tolerance
        );
        const objectiveError = Number(
          (candidate as { objective_error_pct?: number } | undefined)?.objective_error_pct
        );
        const stage0Ric = resolveDownloadUrl(artifacts?.stage0_ric || artifacts?.ric);
        const stage0Eng = resolveDownloadUrl(artifacts?.stage0_eng || artifacts?.eng);
        const stage1Ric = resolveDownloadUrl(artifacts?.stage1_ric);
        const stage1Eng = resolveDownloadUrl(artifacts?.stage1_eng);
        const format = (value: number | null | undefined, unit: string) =>
          Number.isFinite(value) ? `${Number(value).toFixed(2)} ${unit}` : "N/A";
        const outcomeNote =
          withinTolerance || !Number.isFinite(objectiveError)
            ? ""
            : `<div class="download-muted">Best effort: objective error ${objectiveError.toFixed(
                1
              )}%</div>`;
        const renderStageCard = (stageKey: "stage0" | "stage1", stage: Record<string, unknown>) => {
          const totalImpulse = Number(stage.total_impulse);
          const peakMassFlux = Number(stage.peak_mass_flux);
          const rawPressure = Number(
            (stage as { peak_pressure_psi?: number }).peak_pressure_psi ??
              stage.peak_chamber_pressure ??
              stage.max_pressure ??
              stage.max_pressure_pa
          );
          const pressure =
            Number.isFinite(rawPressure) && rawPressure > 10000
              ? rawPressure / 6894.757
              : rawPressure;
          const kn = Number(stage.peak_kn ?? stage.max_kn);
          const motorMass = Number(stage.propellant_mass_lb);
          return `
            <div class="results-stage">
              <div class="results-stage-label">STAGE ${stageKey === "stage0" ? "0" : "1"}</div>
              <div class="results-grid">
                <div class="result-item"><span>TOTAL IMPULSE</span><strong>${format(
                  totalImpulse,
                  "N·s"
                )}</strong></div>
                <div class="result-item"><span>PEAK MASS FLUX</span><strong>${format(
                  peakMassFlux,
                  "kg/m²·s"
                )}</strong></div>
                <div class="result-item"><span>NMAX</span><strong>${format(
                  Number(candidate?.max_accel_m_s2),
                  "m/s²"
                )}</strong></div>
                <div class="result-item"><span>PRESSURE</span><strong>${format(
                  pressure,
                  "psi"
                )}</strong></div>
                <div class="result-item"><span>K_N</span><strong>${format(kn, "")}</strong></div>
                <div class="result-item"><span>TOTAL MOTOR MASS</span><strong>${format(
                  motorMass,
                  "lb"
                )}</strong></div>
              </div>
            </div>
          `;
        };

        const stage0 = (stageMetrics.stage0 as Record<string, unknown> | undefined) || metrics;
        const stage1 = stageMetrics.stage1 as Record<string, unknown> | undefined;
        const missionImpulseRow =
          Number.isFinite(estimatedTotalImpulse) && estimatedTotalImpulse > 0
            ? `<div class="result-item"><span>TOTAL IMPULSE (MISSION)</span><strong>${format(
                estimatedTotalImpulse,
                "N·s"
              )}</strong></div>`
            : "";
        const downloadLinks = artifacts
          ? `
            ${stage0Ric ? `<a class="download-link" href="#" data-download="${stage0Ric}">.ric (stage 0)</a>` : ""}
            ${stage0Eng ? `<a class="download-link" href="#" data-download="${stage0Eng}">.eng (stage 0)</a>` : ""}
            ${stage1Ric ? `<a class="download-link" href="#" data-download="${stage1Ric}">.ric (stage 1)</a>` : ""}
            ${stage1Eng ? `<a class="download-link" href="#" data-download="${stage1Eng}">.eng (stage 1)</a>` : ""}
          `
          : `<div class="download-muted">Download links unavailable.</div>`;
        subPageContent.innerHTML = `
          <div class="subpage-form" data-form="mission-results">
            <div class="form-title">RESULTS</div>
            <div class="form-subtitle">MISSION TARGET OUTPUT</div>
            <div class="results-grid">
              ${missionImpulseRow}
            </div>
            <div class="results-stages">
              ${renderStageCard("stage0", stage0)}
              ${stage1 ? renderStageCard("stage1", stage1) : ""}
            </div>
            <div class="download-box">
              <div class="download-title">DOWNLOAD FILES</div>
              <div class="download-links">${downloadLinks}</div>
              ${outcomeNote}
            </div>
          </div>
        `;
        const downloadsContainer = subPageContent.querySelector(".download-links");
        if (downloadsContainer) {
          downloadsContainer.addEventListener("click", (event) => {
            const target = event.target as HTMLElement | null;
            const anchor = target?.closest("a.download-link") as HTMLAnchorElement | null;
            if (!anchor) return;
            event.preventDefault();
            const href = anchor.getAttribute("data-download") || "";
            triggerDownload(href);
          });
        }
      } else if (type === "SYSTEM" || type === "VEHICLE") {
        const isVehiclePage = type === "VEHICLE";
        let hasLockedTarget = false;
        document.body.classList.add("holo-active");
        document.body.classList.add("grid-only");
        subPageContent.innerHTML = isVehiclePage
          ? `
          <form class="subpage-form" data-form="vehicle-info" novalidate>
            <div class="arx-step active" id="mission-step-2">
              <div class="form-title">VEHICLE INFO</div>
              <div class="form-subtitle">DEFINE THE CURRENT VEHICLE PARAMETERS</div>
              <div class="arx-field">
                <input type="number" name="total_mass_lb" placeholder=" " min="0" step="any" required />
                <label>TOTAL MASS (LB)</label>
                <div class="field-hint">Example: 120</div>
              </div>
              <div class="arx-field">
                <input type="number" name="rocket_length_in" placeholder=" " min="0" step="any" required />
                <label>ROCKET LENGTH (IN)</label>
                <div class="field-hint">Example: 96</div>
              </div>
              <div class="arx-field">
                <input type="number" name="ref_diameter_in" placeholder=" " min="0" step="any" required />
                <label>REFERENCE DIAMETER (IN)</label>
                <div class="field-hint">Example: 6.5</div>
              </div>
              <div class="arx-field">
                <input type="number" name="stage_count" placeholder=" " min="1" step="1" required />
                <label>STAGE COUNT</label>
                <div class="field-hint">Example: 2</div>
              </div>
              <div class="arx-field">
                <input type="number" name="separation_delay_s" placeholder=" " min="0" step="any" required />
                <label>SEPARATION DELAY (S)</label>
              </div>
              <div class="arx-field">
                <input type="number" name="ignition_delay_s" placeholder=" " min="0" step="any" required />
                <label>IGNITION DELAY (S)</label>
              </div>
              <div class="form-status" id="mission-status-2"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" id="mission-back-2">Back</button>
                <button type="button" class="arx-btn" id="mission-continue-2">Continue</button>
              </div>
            </div>

            <div class="arx-step" id="mission-step-2b">
              <div class="form-title">ROCKET PROFILE</div>
              <div class="form-subtitle">VERIFY ORK VALUES + SET PER-STAGE LENGTH</div>
              <div class="arx-field">
                <input type="number" name="ork_length_in" placeholder=" " min="0" step="any" disabled />
                <label>ORK MAX LENGTH (IN)</label>
              </div>
              <div class="arx-field">
                <input type="number" name="ork_mass_lb" placeholder=" " min="0" step="any" disabled />
                <label>ORK TOTAL MASS (LB)</label>
              </div>
              <div class="arx-field">
                <input type="number" name="stage0_length_in" placeholder=" " min="0" step="any" required />
                <label>STAGE 0 LENGTH (IN)</label>
                <div class="field-hint">Allowed tolerance: ±6 in</div>
              </div>
              <div class="arx-field" id="stage1-length-field">
                <input type="number" name="stage1_length_in" placeholder=" " min="0" step="any" />
                <label>STAGE 1 LENGTH (IN)</label>
                <div class="field-hint">Allowed tolerance: ±6 in</div>
              </div>
              <div class="form-status" id="mission-status-2b"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" id="mission-back-2b">Back</button>
                <button type="button" class="arx-btn" id="mission-continue-2b">Continue</button>
              </div>
            </div>

            <div class="arx-step" id="mission-step-3">
              <div class="form-title">ROCKET CONSTRAINTS</div>
              <div class="form-subtitle">DEFINE MAXIMUM CONSTRAINTS</div>
              <div class="arx-field">
                <input type="number" name="max_pressure_psi" placeholder=" " min="0" step="any" required />
                <label>MAX PRESSURE (PSI)</label>
              </div>
            <div class="arx-field">
              <input type="number" name="max_kn" placeholder=" " min="0" step="any" required />
              <label>MAX K_N</label>
              <div class="field-hint">Ratio of burning area to throat area</div>
            </div>
            <div class="arx-field">
              <input type="number" name="separation_delay_s" placeholder=" " min="0" step="any" required />
              <label>SEPARATION DELAY (S)</label>
            </div>
            <div class="arx-field">
              <input type="number" name="ignition_delay_s" placeholder=" " min="0" step="any" required />
              <label>IGNITION DELAY (S)</label>
            </div>
            <div class="arx-field">
              <input
                type="number"
                name="stage_count_constraints"
                placeholder=" "
                min="1"
                step="1"
                required
              />
              <label>STAGE COUNT</label>
              <div class="field-hint">Example: 2</div>
            </div>
              <div class="form-status" id="mission-status-3"></div>
              <div class="arx-form-actions" id="mission-actions">
                <button type="button" class="arx-btn" id="mission-back-3">Back</button>
                <button type="button" class="arx-btn" id="mission-continue-3">Continue</button>
                <div class="mini-reactor-loader" id="mission-loader" aria-hidden="true"></div>
              </div>
              <div class="mission-results" id="mission-results"></div>
            </div>
          </form>
        `
          : `
          <form class="subpage-form" data-form="mission-target" novalidate>
            <div class="arx-step active" id="mission-step-1">
              <div class="form-title">TARGET PROFILE</div>
              <div class="form-subtitle">
                WHAT IS THE MAXIMUM APOGEE AND VELOCITY THAT YOU WANT YOUR ROCKET TO ACHIEVE?
              </div>
              <div class="arx-field">
                <input type="number" name="max_apogee_ft" placeholder=" " min="0" step="any" required />
                <label>MAX APOGEE (FT)</label>
                <div class="field-hint">Example: 30000</div>
              </div>
              <div class="mission-helper" id="apogee-helper">≈ 0 ft</div>
              <div class="mission-warning" id="apogee-warning"></div>
              <div class="arx-field">
                <input type="number" name="max_velocity_m_s" placeholder=" " min="0" step="any" required />
                <label>MAX VELOCITY (M/S)</label>
                <div class="field-hint">Example: 700</div>
              </div>
              <div class="mission-helper" id="velocity-helper">≈ Mach 0.00</div>
              <div class="mission-warning" id="velocity-warning"></div>
              <div class="confidence-meter" id="confidence-meter">
                SYSTEM CONFIDENCE:
                <span class="meter-bar ok" id="confidence-bar">██████░░░</span>
                <span class="meter-value" id="confidence-value">78%</span>
              </div>
              <div class="mission-presets">
                <button type="button" class="preset-btn" data-preset="low">LOW-ALT TEST</button>
                <button type="button" class="preset-btn" data-preset="sound">SOUNDING ROCKET</button>
                <button type="button" class="preset-btn" data-preset="sub">SUB-ORBITAL</button>
                <button type="button" class="preset-btn" data-preset="maxq">MAX-Q STRESS</button>
              </div>
              <div class="preset-status" id="preset-status"></div>
              <div class="ambient-text" id="ambient-text">Analyzing ascent envelope…</div>
              <div class="form-status" id="mission-status-1"></div>
              <div class="panel-footer">
                <div class="arx-form-actions">
                  <button type="button" class="arx-btn mission-continue" id="mission-continue-1">
                    AWAITING TARGET LOCK
                  </button>
                </div>
              </div>
            </div>
          </form>
        `;

        const step1 = subPageContent.querySelector("#mission-step-1") as HTMLElement | null;
        const step2 = subPageContent.querySelector("#mission-step-2") as HTMLElement | null;
        const step2b = subPageContent.querySelector("#mission-step-2b") as HTMLElement | null;
        const step3 = subPageContent.querySelector("#mission-step-3") as HTMLElement | null;
        const status1 = subPageContent.querySelector("#mission-status-1") as HTMLElement | null;
        const status2 = subPageContent.querySelector("#mission-status-2") as HTMLElement | null;
        const status2b = subPageContent.querySelector("#mission-status-2b") as HTMLElement | null;
        const status3 = subPageContent.querySelector("#mission-status-3") as HTMLElement | null;
        const loader = subPageContent.querySelector("#mission-loader") as HTMLElement | null;
        const resultsSlot = subPageContent.querySelector("#mission-results") as HTMLElement | null;
        const actions = subPageContent.querySelector("#mission-actions") as HTMLElement | null;

        const startMissionProgress = () => {
          if (!loader) return;
          const existingTimer = Number(loader.dataset.progressTimer);
          if (Number.isFinite(existingTimer)) {
            window.clearInterval(existingTimer);
          }
          loader.classList.add("active");
          loader.classList.add("progressing");
          loader.dataset.progressStart = String(Date.now());
          loader.dataset.progressTimeout = String(MISSION_TIMEOUT_MS);
          loader.style.setProperty("--progress", "2");
          const timerId = window.setInterval(() => {
            const start = Number(loader.dataset.progressStart);
            const timeout = Number(loader.dataset.progressTimeout);
            if (!Number.isFinite(start) || !Number.isFinite(timeout) || timeout <= 0) return;
            const elapsed = Date.now() - start;
            const pct = Math.min(90, Math.max(2, (elapsed / timeout) * 90));
            loader.style.setProperty("--progress", `${pct}`);
          }, 500);
          loader.dataset.progressTimer = String(timerId);
        };

        const stopMissionProgress = (finalPct?: number) => {
          if (!loader) return;
          const existingTimer = Number(loader.dataset.progressTimer);
          if (Number.isFinite(existingTimer)) {
            window.clearInterval(existingTimer);
          }
          delete loader.dataset.progressTimer;
          delete loader.dataset.progressStart;
          delete loader.dataset.progressTimeout;
          if (typeof finalPct === "number" && Number.isFinite(finalPct)) {
            loader.style.setProperty("--progress", `${finalPct}`);
          }
          loader.classList.remove("progressing");
        };

        const showStep = (step: number) => {
          [step1, step2, step2b, step3].forEach((el, index) => {
            if (!el) return;
            if (index === step) {
              el.classList.add("active");
            } else {
              el.classList.remove("active");
            }
          });
        };

        const updateConstraintsContinue = () => {
          if (!continue3) return;
          const maxPressure = getNumberValue("max_pressure_psi");
          const maxKn = getNumberValue("max_kn");
          const refDiameter = getNumberValue("ref_diameter_in");
          const rocketLength = getNumberValue("rocket_length_in");
          const totalMass = getNumberValue("total_mass_lb");
          const stageCount = getStageCountValue();
          const separationDelay = getNumberValue("separation_delay_s");
          const ignitionDelay = getNumberValue("ignition_delay_s");

          const hasBasics =
            Number.isFinite(maxPressure) &&
            maxPressure > 0 &&
            Number.isFinite(maxKn) &&
            maxKn > 0 &&
            Number.isFinite(refDiameter) &&
            refDiameter > 0 &&
            Number.isFinite(rocketLength) &&
            rocketLength > 0 &&
            Number.isFinite(totalMass) &&
            totalMass > 0 &&
            Number.isFinite(stageCount) &&
            stageCount > 0 &&
            Number.isFinite(separationDelay) &&
            separationDelay >= 0 &&
            Number.isFinite(ignitionDelay) &&
            ignitionDelay >= 0;

          const isValid = hasBasics;
          continue3.style.display = isValid ? "" : "none";
          continue3.disabled = !isValid;
        };

        window.setTimeout(() => {
          document.body.classList.remove("grid-only");
          document.body.classList.add("panel-active");
          if (type === "ARMOR") {
            window.location.assign("/module-r");
          }
        }, 1000);

        const goToVehicleInfo = () => {
          const apogee = getNumberValue("max_apogee_ft");
          const velocity = getNumberValue("max_velocity_m_s");
          if (Number.isFinite(apogee) && apogee > 0 && Number.isFinite(velocity) && velocity > 0) {
            window.localStorage.setItem(
              "arx_target_profile",
              JSON.stringify({ apogee, velocity })
            );
          }
          const useOrk =
            window.localStorage.getItem("arx_use_ork") === "true" ||
            Boolean(window.localStorage.getItem("arx_ork_vehicle_profile"));
          if (useOrk) {
            window.localStorage.setItem("arx_skip_vehicle", "true");
            if (window.location.hash !== "#rocket-constraints") {
              window.location.hash = "rocket-constraints";
            }
            pendingSubPageType = "VEHICLE";
            revealPendingSubPage();
            return;
          }
          if (window.location.hash !== "#vehicle-info") {
            window.location.hash = "vehicle-info";
          }
          pendingSubPageType = "VEHICLE";
          revealPendingSubPage();
        };
        const goToTargetProfile = () => {
          if (window.location.hash !== "#mission-target") {
            window.location.hash = "mission-target";
          }
          pendingSubPageType = "SYSTEM";
          revealPendingSubPage();
        };

        const getInputValue = (name: string) => {
          const input = subPageContent.querySelector(
            `input[name="${name}"]`
          ) as HTMLInputElement | null;
          return input ? input.value.trim() : "";
        };

        const getNumberValue = (name: string) => {
          const raw = getInputValue(name);
          if (!raw) return NaN;
          const value = Number(raw);
          return Number.isFinite(value) ? value : NaN;
        };
        const getStageCountValue = () => {
          const override = Math.floor(getNumberValue("stage_count_constraints"));
          if (Number.isFinite(override) && override > 0) return override;
          return Math.floor(getNumberValue("stage_count"));
        };

        const stageCountInput = subPageContent.querySelector(
          'input[name="stage_count"]'
        ) as HTMLInputElement | null;
        const stage1LengthField = subPageContent.querySelector(
          "#stage1-length-field"
        ) as HTMLElement | null;
        const updateStageLengthVisibility = () => {
          const stageCount = getStageCountValue();
          if (!stage1LengthField) return;
          stage1LengthField.style.display = stageCount > 1 ? "" : "none";
        };
        stageCountInput?.addEventListener("input", () => {
          updateConstraintsContinue();
          updateStageLengthVisibility();
        });

        const continue1 = subPageContent.querySelector("#mission-continue-1") as HTMLButtonElement | null;
        const continue2 = subPageContent.querySelector("#mission-continue-2") as HTMLButtonElement | null;
        const continue2b = subPageContent.querySelector("#mission-continue-2b") as HTMLButtonElement | null;
        const continue3 = subPageContent.querySelector("#mission-continue-3") as HTMLButtonElement | null;
        const back2 = subPageContent.querySelector("#mission-back-2") as HTMLButtonElement | null;
        const back2b = subPageContent.querySelector("#mission-back-2b") as HTMLButtonElement | null;
        const back3 = subPageContent.querySelector("#mission-back-3") as HTMLButtonElement | null;
        const ensureMissionNoticeModal = () => {
          let modal = subPageContent.querySelector(".mission-notice-modal") as HTMLElement | null;
          if (modal) return modal;
          modal = document.createElement("div");
          modal.className = "mission-notice-modal";
          modal.innerHTML = `
            <div class="mission-notice-modal-panel">
              <div class="panel-header">TIME ESTIMATE</div>
              <div class="modal-text">Per stage, time is estimated 5 minutes ± 1 minute.</div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="mission-notice-ok">OK</button>
              </div>
            </div>
          `;
          const close = () => {
            modal?.setAttribute("data-open", "false");
          };
          modal.addEventListener("click", (event) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;
            if (
              target === modal ||
              target.closest('[data-action="mission-notice-ok"]')
            ) {
              close();
            }
          });
          subPageContent.appendChild(modal);
          return modal;
        };
        const openMissionNoticeModal = () => {
          const modal = ensureMissionNoticeModal();
          modal.setAttribute("data-open", "true");
        };

        // Target profile enhancements (step 1 only)
        const apogeeInput = subPageContent.querySelector(
          'input[name="max_apogee_ft"]'
        ) as HTMLInputElement | null;
        const velocityInput = subPageContent.querySelector(
          'input[name="max_velocity_m_s"]'
        ) as HTMLInputElement | null;
        const apogeeHelper = subPageContent.querySelector("#apogee-helper") as HTMLElement | null;
        const velocityHelper = subPageContent.querySelector("#velocity-helper") as HTMLElement | null;
        const rightHolo = document.getElementById("holo-side-right") as HTMLElement | null;
        const engineContainer = document.getElementById("engine-holo-container") as HTMLElement | null;
        const apogeeWarning = subPageContent.querySelector("#apogee-warning") as HTMLElement | null;
        const velocityWarning = subPageContent.querySelector("#velocity-warning") as HTMLElement | null;
        const confidenceBar = subPageContent.querySelector("#confidence-bar") as HTMLElement | null;
        const confidenceValue = subPageContent.querySelector("#confidence-value") as HTMLElement | null;
        const ambientText = subPageContent.querySelector("#ambient-text") as HTMLElement | null;
        const presetButtons = subPageContent.querySelectorAll(".preset-btn");
        const presetStatus = subPageContent.querySelector("#preset-status") as HTMLElement | null;
        const telemetryContainer = document.getElementById(
          "telemetry-graph-left"
        ) as HTMLElement | null;

        const applyOrkProfile = () => {
          const stored = window.localStorage.getItem("arx_ork_vehicle_profile");
          if (!stored) return;
          try {
            const profile = JSON.parse(stored) as {
              rocket_length_in?: number;
              ref_diameter_in?: number;
              total_mass_lb?: number;
            };
            const massInput = subPageContent.querySelector(
              'input[name="total_mass_lb"]'
            ) as HTMLInputElement | null;
            const lengthInput = subPageContent.querySelector(
              'input[name="rocket_length_in"]'
            ) as HTMLInputElement | null;
            const diameterInput = subPageContent.querySelector(
              'input[name="ref_diameter_in"]'
            ) as HTMLInputElement | null;
            const stageCountInputEl = subPageContent.querySelector(
              'input[name="stage_count"]'
            ) as HTMLInputElement | null;
            const stageCountOverrideEl = subPageContent.querySelector(
              'input[name="stage_count_constraints"]'
            ) as HTMLInputElement | null;
            const separationInput = subPageContent.querySelector(
              'input[name="separation_delay_s"]'
            ) as HTMLInputElement | null;
            const ignitionInput = subPageContent.querySelector(
              'input[name="ignition_delay_s"]'
            ) as HTMLInputElement | null;
            const orkLengthInput = subPageContent.querySelector(
              'input[name="ork_length_in"]'
            ) as HTMLInputElement | null;
            const orkMassInput = subPageContent.querySelector(
              'input[name="ork_mass_lb"]'
            ) as HTMLInputElement | null;
            const stage0LengthInput = subPageContent.querySelector(
              'input[name="stage0_length_in"]'
            ) as HTMLInputElement | null;
            const stage1LengthInput = subPageContent.querySelector(
              'input[name="stage1_length_in"]'
            ) as HTMLInputElement | null;
            const rocketLengthIn = Number(profile.rocket_length_in);
            const totalMassLb = Number(profile.total_mass_lb);
            if (massInput && Number.isFinite(totalMassLb)) {
              massInput.value = String(totalMassLb);
            }
            if (lengthInput && Number.isFinite(rocketLengthIn)) {
              lengthInput.value = String(rocketLengthIn);
            }
            if (diameterInput && Number.isFinite(profile.ref_diameter_in)) {
              diameterInput.value = String(profile.ref_diameter_in);
            }
            if (orkLengthInput && Number.isFinite(rocketLengthIn)) {
              orkLengthInput.value = String(rocketLengthIn);
            }
            if (orkMassInput && Number.isFinite(totalMassLb)) {
              orkMassInput.value = String(totalMassLb);
            }
            if (stageCountInputEl && !stageCountInputEl.value) {
              stageCountInputEl.value = "2";
            }
            if (stageCountOverrideEl && !stageCountOverrideEl.value) {
              stageCountOverrideEl.value = "2";
            }
            if (separationInput && !separationInput.value) {
              separationInput.value = "5";
            }
            if (ignitionInput && !ignitionInput.value) {
              ignitionInput.value = "5";
            }
            if (Number.isFinite(rocketLengthIn) && stage0LengthInput && !stage0LengthInput.value) {
              const stageCount = stageCountInputEl ? Number(stageCountInputEl.value) || 1 : 1;
              stage0LengthInput.value = String(rocketLengthIn / Math.max(stageCount, 1));
            }
            if (Number.isFinite(rocketLengthIn) && stage1LengthInput && !stage1LengthInput.value) {
              const stageCount = stageCountInputEl ? Number(stageCountInputEl.value) || 1 : 1;
              stage1LengthInput.value = String(rocketLengthIn / Math.max(stageCount, 1));
            }
          } catch (error) {
            console.warn("Invalid arx_ork_vehicle_profile JSON", error);
          }
        };

        const systemMessages = [
          "Analyzing ascent envelope…",
          "Cross-checking aerodynamic limits…",
          "Trajectory within recoverable bounds.",
        ];
        let systemMessageIndex = 0;
        let systemMessageInterval: number | null = null;

        const clamp = (value: number, min: number, max: number) =>
          Math.max(min, Math.min(max, value));
        const toMach = (velocity: number) => velocity / 343;

        const formatNumber = (value: number) =>
          Number.isFinite(value) ? value.toLocaleString("en-US") : "0";

        let sideHoloAnimId: number | null = null;
        let currentPreset: string | null = null;
        let holoPulse = 0;

        const animateSideHolograms = () => {
          holoPulse += 0.02;
          sideHoloAnimId = requestAnimationFrame(animateSideHolograms);
        };

        const initEngineHologram = () => {
          if (!engineContainer || engineRenderer) return;
          const rect = engineContainer.getBoundingClientRect();
          const width = Math.max(260, Math.floor(rect.width));
          const height = Math.max(260, Math.floor(rect.height));

          engineScene = new THREE.Scene();
          engineCamera = new THREE.PerspectiveCamera(50, width / height, 0.1, 1000);
          engineCamera.position.set(0, 1, 8);

          engineRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
          engineRenderer.setSize(width, height);
          engineRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
          engineRenderer.setClearColor(0x000000, 0);
          engineRenderer.domElement.style.background = "transparent";
          engineContainer.appendChild(engineRenderer.domElement);

          const holoMaterial = new THREE.ShaderMaterial({
            uniforms: {
              time: { value: 0.0 },
              glowColor: { value: new THREE.Color(0x00e6a8) },
            },
            vertexShader: `
              varying vec3 vNormal;
              varying vec3 vPosition;
              void main() {
                vNormal = normalize(normalMatrix * normal);
                vPosition = position;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
              }
            `,
            fragmentShader: `
              uniform float time;
              uniform vec3 glowColor;
              varying vec3 vNormal;
              varying vec3 vPosition;
              void main() {
                float viewLine = dot(vNormal, vec3(0.0, 0.0, 1.0));
                float fresnel = pow(1.0 - abs(viewLine), 2.0);
                float scanline = sin(vPosition.y * 10.0 + time * 5.0) * 0.05 + 0.95;
                float depthFade = smoothstep(-1.5, 1.5, vPosition.y);
                float opacity = fresnel * scanline * depthFade * 0.18;
                gl_FragColor = vec4(glowColor, opacity);
              }
            `,
            transparent: true,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          });

          const wireMaterial = new THREE.LineBasicMaterial({
            color: 0x00e6a8,
            transparent: true,
            opacity: 0.35,
          });

          const engineGroup = new THREE.Group();
          const addPart = (geo: any, yPos: number) => {
            const mesh = new THREE.Mesh(geo, holoMaterial);
            const wire = new THREE.LineSegments(new THREE.WireframeGeometry(geo), wireMaterial);
            mesh.position.y = yPos;
            mesh.add(wire);
            engineGroup.add(mesh);
          };

          addPart(new THREE.CylinderGeometry(0.7, 1.6, 2.5, 32, 12, true), -1.5);
          addPart(new THREE.CylinderGeometry(0.7, 0.7, 1.2, 32, 6), 0.35);
          addPart(new THREE.TorusGeometry(0.8, 0.15, 16, 100), 1.0);
          addPart(new THREE.CylinderGeometry(1.0, 1.0, 0.2, 32), 1.3);

          engineScene.add(engineGroup);

          const renderTarget = new THREE.WebGLRenderTarget(width, height, {
            type: THREE.HalfFloatType,
            format: THREE.RGBAFormat,
            colorSpace: THREE.SRGBColorSpace,
          });

          engineComposer = new EffectComposer(engineRenderer, renderTarget);
          const renderPass = new RenderPass(engineScene, engineCamera);
          renderPass.clearColor = new THREE.Color(0, 0, 0);
          renderPass.clearAlpha = 0;
          engineComposer.addPass(renderPass);

          const bloomPass = new UnrealBloomPass(
            new THREE.Vector2(width, height),
            1.5,
            0.4,
            0.85
          );
          bloomPass.threshold = 0;
          bloomPass.strength = 0.35;
          bloomPass.radius = 0.15;
          engineComposer.addPass(bloomPass);

          engineControls = new OrbitControls(engineCamera, engineRenderer.domElement);
          engineControls.enableDamping = true;
          engineControls.autoRotate = false;
          engineControls.autoRotateSpeed = 0.0;
          engineControls.enableRotate = true;
          engineControls.enableZoom = false;
          engineControls.enablePan = false;
          engineControls.enabled = true;
          engineRenderer.domElement.style.pointerEvents = "auto";

          const clock = new THREE.Clock();
          const renderEngine = () => {
            engineAnimationId = requestAnimationFrame(renderEngine);
            const delta = clock.getElapsedTime();
            holoMaterial.uniforms.time.value = delta;
            engineGroup.position.y = Math.sin(delta * 0.5) * 0.1;
            engineControls?.update();
            engineComposer?.render();
          };
          renderEngine();

          engineResizeObserver = new ResizeObserver(() => {
            if (!engineContainer || !engineRenderer || !engineComposer || !engineCamera) return;
            const nextRect = engineContainer.getBoundingClientRect();
            const nextWidth = Math.max(260, Math.floor(nextRect.width));
            const nextHeight = Math.max(260, Math.floor(nextRect.height));
            engineRenderer.setSize(nextWidth, nextHeight);
            engineComposer.setSize(nextWidth, nextHeight);
            engineCamera.aspect = nextWidth / nextHeight;
            engineCamera.updateProjectionMatrix();
          });
          engineResizeObserver.observe(engineContainer);

        };

        if (telemetryContainer) {
          telemetryGraph?.dispose();
          telemetryGraph = new FlightTelemetryGraph(telemetryContainer);
          const stored = window.localStorage.getItem("arx_target_profile");
          if (stored) {
            try {
              const parsed = JSON.parse(stored) as { apogee?: number; velocity?: number };
              if (Number.isFinite(parsed.apogee) && Number.isFinite(parsed.velocity)) {
                telemetryGraph.setInputs(Number(parsed.apogee), Number(parsed.velocity));
              }
            } catch {
              // ignore malformed storage
            }
          }
        }

        const computePresetConfidence = (
          apogee: number,
          velocity: number,
          preset: { apogee: number; velocity: number; apogeeTol: number; velocityTol: number }
        ) => {
          const apogeeDelta = Math.abs(apogee - preset.apogee);
          const velocityDelta = Math.abs(velocity - preset.velocity);
          const apogeeScore = clamp(1 - apogeeDelta / preset.apogeeTol, 0, 1);
          const velocityScore = clamp(1 - velocityDelta / preset.velocityTol, 0, 1);
          const blended = (apogeeScore * 0.6 + velocityScore * 0.4) * 100;
          return Math.round(clamp(blended, 5, 99));
        };

        const updateConfidence = (apogee: number, velocity: number) => {
          const missingValues = !Number.isFinite(apogee) || apogee <= 0 || !Number.isFinite(velocity) || velocity <= 0;
          let confidence = 0;
          if (!missingValues && currentPreset && presets[currentPreset]) {
            confidence = computePresetConfidence(apogee, velocity, presets[currentPreset]);
          } else if (!missingValues) {
            let base = 100;
            if (apogee > 300000 || velocity > 2400) base -= 35;
            if (apogee < 1000 || velocity < 80) base -= 25;
            if (apogee > 200000 && velocity > 1800) base -= 15;
            confidence = Math.round(clamp(base, 10, 99));
          }

          if (confidenceValue) confidenceValue.textContent = `${confidence}%`;
          if (confidenceBar) {
            const blocks = Math.round((confidence / 100) * 9);
            confidenceBar.textContent = "█".repeat(blocks) + "░".repeat(9 - blocks);
            confidenceBar.classList.remove("ok", "warn", "bad");
            if (confidence > 70) confidenceBar.classList.add("ok");
            else if (confidence > 40) confidenceBar.classList.add("warn");
            else confidenceBar.classList.add("bad");
          }
        };

        const updateTargetProfileUI = () => {
          const apogee = Number(apogeeInput?.value || 0);
          const velocity = Number(velocityInput?.value || 0);
          if (!Number.isFinite(apogee) || apogee <= 0 || !Number.isFinite(velocity) || velocity <= 0) {
            currentPreset = null;
          }

          if (apogeeHelper) {
            apogeeHelper.textContent = `≈ ${formatNumber(apogee)} ft`;
          }
          if (velocityHelper) {
            velocityHelper.textContent = `≈ Mach ${toMach(velocity).toFixed(2)}`;
          }

          if (apogeeWarning) {
            apogeeWarning.textContent =
              apogee > 300000 ? "⚠ TRAJECTORY INSTABILITY DETECTED" : "";
            apogeeWarning.classList.toggle("visible", Boolean(apogeeWarning.textContent));
          }
          if (velocityWarning) {
            velocityWarning.textContent =
              velocity > 2200 ? "Recommend reducing velocity by ~10%" : "";
            velocityWarning.classList.toggle("visible", Boolean(velocityWarning.textContent));
          }

          updateConfidence(apogee, velocity);
          engineHighlight = 1;
          telemetryGraph?.setInputs(apogee, velocity);

          const valid =
            Number.isFinite(apogee) &&
            apogee > 0 &&
            Number.isFinite(velocity) &&
            velocity > 0;
          if (continue1) {
            continue1.textContent = valid ? "TARGET LOCKED → CONTINUE" : "AWAITING TARGET LOCK";
            continue1.classList.toggle("ready", valid);
          }
        };

        if (apogeeInput || velocityInput) {
          apogeeInput?.addEventListener("input", updateTargetProfileUI);
          velocityInput?.addEventListener("input", updateTargetProfileUI);
          updateTargetProfileUI();
        }
        applyOrkProfile();
        updateStageLengthVisibility();

        if (isVehiclePage) {
          hasLockedTarget = true;
        }
        const skipVehicle = window.localStorage.getItem("arx_skip_vehicle") === "true";
        if (skipVehicle && isVehiclePage) {
          window.localStorage.removeItem("arx_skip_vehicle");
          showStep(2);
          updateConstraintsContinue();
        }
        if (window.location.hash === "#vehicle-info" && !isVehiclePage && hasLockedTarget) {
          goToVehicleInfo();
        }
        window.addEventListener("hashchange", () => {
          if (window.location.hash === "#vehicle-info" && !isVehiclePage && hasLockedTarget) {
            goToVehicleInfo();
          }
        });

        if (!sideHoloAnimId) {
          sideHoloAnimId = requestAnimationFrame(animateSideHolograms);
        }
        requestAnimationFrame(() => initEngineHologram());

        rightHolo?.addEventListener("mouseenter", () => {
          rightHolo.classList.add("holo-focus");
        });
        rightHolo?.addEventListener("mouseleave", () => {
          rightHolo.classList.remove("holo-focus");
        });

        if (ambientText) {
          if (systemMessageInterval) window.clearInterval(systemMessageInterval);
          systemMessageInterval = window.setInterval(() => {
            systemMessageIndex = (systemMessageIndex + 1) % systemMessages.length;
            ambientText.textContent = systemMessages[systemMessageIndex];
          }, 3500);
        }

        const presets: Record<
          string,
          { apogee: number; velocity: number; apogeeTol: number; velocityTol: number }
        > = {
          low: { apogee: 12000, velocity: 320, apogeeTol: 5000, velocityTol: 150 },
          sound: { apogee: 60000, velocity: 720, apogeeTol: 15000, velocityTol: 250 },
          sub: { apogee: 250000, velocity: 1300, apogeeTol: 50000, velocityTol: 400 },
          maxq: { apogee: 40000, velocity: 1800, apogeeTol: 10000, velocityTol: 300 },
        };
        presetButtons.forEach((button) => {
          button.addEventListener("click", () => {
            const key = (button as HTMLElement).dataset.preset || "";
            const preset = presets[key];
            if (!preset) return;
            currentPreset = key;
            if (presetStatus) {
              presetStatus.textContent = `LOADING ${button.textContent} PROFILE…`;
              presetStatus.classList.add("active");
            }
            window.setTimeout(() => {
              if (apogeeInput) apogeeInput.value = String(preset.apogee);
              if (velocityInput) velocityInput.value = String(preset.velocity);
              updateTargetProfileUI();
              if (presetStatus) {
                presetStatus.textContent = "";
                presetStatus.classList.remove("active");
              }
            }, 600);
          });
        });

        const handleTargetContinue = () => {
          if (status1) status1.textContent = "";
          const apogee = getNumberValue("max_apogee_ft");
          const velocity = getNumberValue("max_velocity_m_s");
          if (!Number.isFinite(apogee) || apogee <= 0 || !Number.isFinite(velocity) || velocity <= 0) {
            if (status1) status1.textContent = "ENTER MAX APOGEE AND MAX VELOCITY.";
            return;
          }
          hasLockedTarget = true;
          goToVehicleInfo();
        };

        continue1?.addEventListener("click", handleTargetContinue);
        const subPageEl = subPageContent as HTMLElement;
        if (subPageEl && subPageEl.dataset.missionContinueBound !== "true") {
          subPageEl.dataset.missionContinueBound = "true";
          subPageEl.addEventListener("click", (event) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;
            const button = target.closest("#mission-continue-1");
            if (!button) return;
            event.preventDefault();
            handleTargetContinue();
          });
        }

        continue2?.addEventListener("click", () => {
          if (status2) status2.textContent = "";
          const totalMass = getNumberValue("total_mass_lb");
          const rocketLength = getNumberValue("rocket_length_in");
          const refDiameter = getNumberValue("ref_diameter_in");
          const stageCount = getStageCountValue();
          const separationDelay = getNumberValue("separation_delay_s");
          const ignitionDelay = getNumberValue("ignition_delay_s");
          if (
            !Number.isFinite(totalMass) ||
            totalMass <= 0 ||
            !Number.isFinite(rocketLength) ||
            rocketLength <= 0 ||
            !Number.isFinite(refDiameter) ||
            refDiameter <= 0 ||
            !Number.isFinite(stageCount) ||
            stageCount <= 0 ||
            !Number.isFinite(separationDelay) ||
            separationDelay < 0 ||
            !Number.isFinite(ignitionDelay) ||
            ignitionDelay < 0
          ) {
            if (status2) status2.textContent = "COMPLETE ALL VEHICLE FIELDS.";
            return;
          }
          const stage0LengthInput = subPageContent.querySelector(
            'input[name="stage0_length_in"]'
          ) as HTMLInputElement | null;
          const stage1LengthInput = subPageContent.querySelector(
            'input[name="stage1_length_in"]'
          ) as HTMLInputElement | null;
          if (stage0LengthInput && !stage0LengthInput.value) {
            stage0LengthInput.value = String(rocketLength / Math.max(stageCount, 1));
          }
          if (stage1LengthInput && !stage1LengthInput.value) {
            stage1LengthInput.value = String(rocketLength / Math.max(stageCount, 1));
          }
          updateStageLengthVisibility();
          showStep(2);
        });
        back2?.addEventListener("click", () => {
          goToTargetProfile();
        });

        continue2b?.addEventListener("click", () => {
          if (status2b) status2b.textContent = "";
          const stageCount = getStageCountValue();
          const stage0Length = getNumberValue("stage0_length_in");
          const stage1Length = getNumberValue("stage1_length_in");
          if (!Number.isFinite(stage0Length) || stage0Length <= 0) {
            if (status2b) status2b.textContent = "ENTER A VALID STAGE 0 LENGTH.";
            return;
          }
          if (stageCount > 1 && (!Number.isFinite(stage1Length) || stage1Length <= 0)) {
            if (status2b) status2b.textContent = "ENTER A VALID STAGE 1 LENGTH.";
            return;
          }
          window.localStorage.setItem(
            "arx_stage_length_targets",
            JSON.stringify({
              stage0_length_in: stage0Length,
              stage1_length_in: stageCount > 1 ? stage1Length : null,
            })
          );
          showStep(3);
          updateConstraintsContinue();
        });
        back2b?.addEventListener("click", () => {
          const useOrk =
            window.localStorage.getItem("arx_use_ork") === "true" ||
            Boolean(window.localStorage.getItem("arx_ork_vehicle_profile"));
          if (useOrk) {
            goToTargetProfile();
          } else {
            showStep(1);
          }
        });

        const renderResults = (candidate: Record<string, unknown>) => {
          if (!resultsSlot) return;
          const nmax = Number(candidate.max_accel_m_s2);
          const metrics = (candidate.metrics as Record<string, unknown> | undefined) || {};
          const stageMetrics = (candidate.stage_metrics as Record<string, unknown> | undefined) || {};
          const estimatedTotalImpulse = Number(
            (candidate as { estimated_total_impulse_ns?: number }).estimated_total_impulse_ns
          );
          const artifacts =
            (candidate.artifact_urls as Record<string, string> | undefined) ||
            (candidate.artifacts as Record<string, string> | undefined);
          const withinTolerance = Boolean((candidate as { within_tolerance?: boolean }).within_tolerance);
          const objectiveError = Number((candidate as { objective_error_pct?: number }).objective_error_pct);

          const format = (value: number, unit: string) =>
            Number.isFinite(value) ? `${value.toFixed(2)} ${unit}` : "N/A";

          const stage0Ric = resolveDownloadUrl(artifacts?.stage0_ric || artifacts?.ric);
          const stage0Eng = resolveDownloadUrl(artifacts?.stage0_eng || artifacts?.eng);
          const stage1Ric = resolveDownloadUrl(artifacts?.stage1_ric);
          const stage1Eng = resolveDownloadUrl(artifacts?.stage1_eng);

          const renderStageCard = (stageKey: "stage0" | "stage1", stage: Record<string, unknown>) => {
            const totalImpulse = Number(stage.total_impulse);
            const peakMassFlux = Number(stage.peak_mass_flux);
            const rawPressure = Number(
              (stage as { peak_pressure_psi?: number }).peak_pressure_psi ??
                stage.peak_chamber_pressure ??
                stage.max_pressure ??
                stage.max_pressure_pa
            );
            const pressure =
              Number.isFinite(rawPressure) && rawPressure > 10000
                ? rawPressure / 6894.757
                : rawPressure;
            const kn = Number(stage.peak_kn);
            const motorMass = Number(stage.propellant_mass_lb);
            return `
              <div class="results-stage">
                <div class="results-stage-label">STAGE ${stageKey === "stage0" ? "0" : "1"}</div>
                <div class="results-grid">
                  <div class="result-item"><span>TOTAL IMPULSE</span><strong>${format(
                    totalImpulse,
                    "N·s"
                  )}</strong></div>
                  <div class="result-item"><span>PEAK MASS FLUX</span><strong>${format(
                    peakMassFlux,
                    "kg/m²·s"
                  )}</strong></div>
                  <div class="result-item"><span>NMAX</span><strong>${format(nmax, "m/s²")}</strong></div>
                  <div class="result-item"><span>PRESSURE</span><strong>${format(
                    pressure,
                    "psi"
                  )}</strong></div>
                  <div class="result-item"><span>K_N</span><strong>${format(kn, "")}</strong></div>
                  <div class="result-item"><span>TOTAL MOTOR MASS</span><strong>${format(
                    motorMass,
                    "lb"
                  )}</strong></div>
                </div>
              </div>
            `;
          };

          const stage0 = (stageMetrics.stage0 as Record<string, unknown> | undefined) || metrics;
          const stage1 = stageMetrics.stage1 as Record<string, unknown> | undefined;
          const missionImpulseRow =
            Number.isFinite(estimatedTotalImpulse) && estimatedTotalImpulse > 0
              ? `<div class="result-item"><span>TOTAL IMPULSE (MISSION)</span><strong>${format(
                  estimatedTotalImpulse,
                  "N·s"
                )}</strong></div>`
              : "";
          const outcomeNote =
            withinTolerance || !Number.isFinite(objectiveError)
              ? ""
              : `<div class="download-muted">Best effort: objective error ${objectiveError.toFixed(1)}%</div>`;
          const downloadLinks = artifacts
            ? `
              ${stage0Ric ? `<a class="download-link" href="#" data-download="${stage0Ric}">.ric (stage 0)</a>` : ""}
              ${stage0Eng ? `<a class="download-link" href="#" data-download="${stage0Eng}">.eng (stage 0)</a>` : ""}
              ${stage1Ric ? `<a class="download-link" href="#" data-download="${stage1Ric}">.ric (stage 1)</a>` : ""}
              ${stage1Eng ? `<a class="download-link" href="#" data-download="${stage1Eng}">.eng (stage 1)</a>` : ""}
            `
            : `<div class="download-muted">Download links unavailable.</div>`;

          resultsSlot.innerHTML = `
            <div class="results-header">
              <div></div>
            </div>
            <div class="results-grid">
              ${missionImpulseRow}
            </div>
            <div class="results-stages">
              ${renderStageCard("stage0", stage0)}
              ${stage1 ? renderStageCard("stage1", stage1) : ""}
            </div>
            <div class="download-box">
              <div class="download-title">DOWNLOAD FILES</div>
              <div class="download-links">${downloadLinks}</div>
              ${outcomeNote}
            </div>
          `;
          resultsSlot.classList.add("visible");
          const downloadsContainer = resultsSlot.querySelector(".download-links");
          if (downloadsContainer) {
            downloadsContainer.addEventListener("click", (event) => {
              const target = event.target as HTMLElement | null;
              const anchor = target?.closest("a.download-link") as HTMLAnchorElement | null;
              if (!anchor) return;
              event.preventDefault();
              const href = anchor.getAttribute("data-download") || "";
              triggerDownload(href);
            });
          }
        };

        const handleMissionStatus = (event: Event) => {
          const detail = (event as CustomEvent).detail as
            | { status: string; job?: { result?: Record<string, unknown> } }
            | undefined;
          if (!detail) return;
          if (detail.status === "start" || detail.status === "submitted" || detail.status === "running") {
            startMissionProgress();
          }
          if (detail.status === "completed" && detail.job?.result) {
            const result = detail.job.result as Record<string, unknown>;
            const motorlib = result.openmotor_motorlib_result as Record<string, unknown> | undefined;
            const ranked = (motorlib?.ranked as Record<string, unknown>[] | undefined) || [];
            const candidates = (motorlib?.candidates as Record<string, unknown>[] | undefined) || [];
            const hasStageData = (entry?: Record<string, unknown>) =>
              Boolean(entry?.stage_metrics || entry?.artifacts || entry?.artifact_urls);
            const findBestCandidateMatch = (target: Record<string, unknown>) => {
              const targetName = target.name;
              const targetMetrics = (target.metrics as Record<string, unknown> | undefined) || {};
              const targetImpulse = Number(targetMetrics.total_impulse);
              const nameMatches = candidates.filter((item) => item.name === targetName);
              if (nameMatches.length === 1) {
                return nameMatches[0];
              }
              let best: Record<string, unknown> | undefined;
              let bestDelta: number | undefined;
              const pool = nameMatches.length ? nameMatches : candidates;
              for (const item of pool) {
                const metrics = (item.metrics as Record<string, unknown> | undefined) || {};
                const impulse = Number(metrics.total_impulse);
                if (!Number.isFinite(targetImpulse) || !Number.isFinite(impulse)) continue;
                const delta = Math.abs(impulse - targetImpulse);
                if (bestDelta === undefined || delta < bestDelta) {
                  bestDelta = delta;
                  best = item;
                }
              }
              return best;
            };
            let candidate = ranked[0] || candidates[0];
            if (candidate && !hasStageData(candidate) && candidates.length) {
              const match = findBestCandidateMatch(candidate);
              if (match) {
                candidate = {
                  ...match,
                  ...candidate,
                  stage_metrics:
                    (match as { stage_metrics?: Record<string, unknown> }).stage_metrics ??
                    (candidate as { stage_metrics?: Record<string, unknown> }).stage_metrics,
                  artifacts:
                    (match as { artifacts?: Record<string, unknown> }).artifacts ??
                    (candidate as { artifacts?: Record<string, unknown> }).artifacts,
                  artifact_urls:
                    (match as { artifact_urls?: Record<string, unknown> }).artifact_urls ??
                    (candidate as { artifact_urls?: Record<string, unknown> }).artifact_urls,
                };
              }
            }
            const estimatedTotalImpulse = Number(
              (result as { estimated_total_impulse_ns?: number }).estimated_total_impulse_ns
            );
            if (candidate && Number.isFinite(estimatedTotalImpulse) && estimatedTotalImpulse > 0) {
              (candidate as { estimated_total_impulse_ns?: number }).estimated_total_impulse_ns =
                estimatedTotalImpulse;
            }
            if (candidate) {
              renderResults(candidate);
            }
            window.localStorage.setItem(
              "arx_mission_target_result",
              JSON.stringify({ job: detail.job })
            );
            if (status3) status3.textContent = "THIS IS DONE.";
            stopMissionProgress(100);
            if (loader) loader.classList.add("active");
            if (actions) actions.classList.add("hidden");
            document.body.classList.remove("grid-mat-active");
            document.getElementById("grid-mat-layer")?.classList.add("grid-mat-hidden");
            window.removeEventListener("arx:mission-target:status", handleMissionStatus as EventListener);
            window.removeEventListener("arx:mission-target:error", handleMissionError as EventListener);
            window.setTimeout(() => {
              pendingSubPageType = "RESULTS";
              window.location.hash = "mission-results";
              stopMissionProgress();
              if (loader) loader.classList.remove("active");
              revealPendingSubPage();
            }, 800);
          }
        };

        const handleMissionError = (event: Event) => {
          const detail = (event as CustomEvent).detail as { message?: string } | undefined;
          if (status3) status3.textContent = detail?.message || "MISSION TARGET FAILED.";
          stopMissionProgress();
          if (loader) loader.classList.remove("active");
          if (continue3) continue3.disabled = false;
          if (continue3) continue3.style.display = "";
          window.removeEventListener("arx:mission-target:status", handleMissionStatus as EventListener);
          window.removeEventListener("arx:mission-target:error", handleMissionError as EventListener);
        };

        continue3?.addEventListener("click", () => {
          openMissionNoticeModal();
          if (status3) status3.textContent = "";
          window.localStorage.removeItem("arx_mission_target_result");
          window.localStorage.removeItem("arx_mission_target_job_id");
          let apogee = getNumberValue("max_apogee_ft");
          let velocity = getNumberValue("max_velocity_m_s");
          if (!Number.isFinite(apogee) || apogee <= 0 || !Number.isFinite(velocity) || velocity <= 0) {
            try {
              const stored = window.localStorage.getItem("arx_target_profile");
              if (stored) {
                const parsed = JSON.parse(stored) as { apogee?: number; velocity?: number };
                if (Number.isFinite(parsed.apogee) && parsed.apogee && apogeeInput) {
                  apogeeInput.value = String(parsed.apogee);
                }
                if (Number.isFinite(parsed.velocity) && parsed.velocity && velocityInput) {
                  velocityInput.value = String(parsed.velocity);
                }
                if (Number.isFinite(parsed.apogee) && parsed.apogee) {
                  apogee = parsed.apogee;
                }
                if (Number.isFinite(parsed.velocity) && parsed.velocity) {
                  velocity = parsed.velocity;
                }
              }
            } catch (error) {
              console.warn("Invalid arx_target_profile JSON", error);
            }
            if (!Number.isFinite(apogee) || apogee <= 0) {
              apogee = getNumberValue("max_apogee_ft");
            }
            if (!Number.isFinite(velocity) || velocity <= 0) {
              velocity = getNumberValue("max_velocity_m_s");
            }
          }
          if (!Number.isFinite(apogee) || apogee <= 0 || !Number.isFinite(velocity) || velocity <= 0) {
            if (status3) status3.textContent = "TARGET PROFILE REQUIRED.";
            return;
          }
          const totalMass = getNumberValue("total_mass_lb");
          const rocketLength = getNumberValue("rocket_length_in");
          const stageCount = getStageCountValue();
          const stage0Length = getNumberValue("stage0_length_in");
          const stage1Length = getNumberValue("stage1_length_in");
          let separationDelay = getNumberValue("separation_delay_s");
          let ignitionDelay = getNumberValue("ignition_delay_s");
          if (!Number.isFinite(separationDelay) || separationDelay < 0) {
            try {
              const stored = window.localStorage.getItem("arx_cdx1_profile");
              if (stored) {
                const parsed = JSON.parse(stored) as {
                  booster_separation_s?: number;
                };
                if (Number.isFinite(parsed.booster_separation_s as number)) {
                  separationDelay = Number(parsed.booster_separation_s);
                }
              }
            } catch (error) {
              console.warn("Invalid arx_cdx1_profile JSON", error);
            }
          }
          if (!Number.isFinite(ignitionDelay) || ignitionDelay < 0) {
            try {
              const stored = window.localStorage.getItem("arx_cdx1_profile");
              if (stored) {
                const parsed = JSON.parse(stored) as {
                  sustainer_ignition_s?: number;
                };
                if (Number.isFinite(parsed.sustainer_ignition_s as number)) {
                  ignitionDelay = Number(parsed.sustainer_ignition_s);
                }
              }
            } catch (error) {
              console.warn("Invalid arx_cdx1_profile JSON", error);
            }
          }
          if (!Number.isFinite(separationDelay) || separationDelay < 0) {
            separationDelay = 5;
          }
          if (!Number.isFinite(ignitionDelay) || ignitionDelay < 0) {
            ignitionDelay = 5;
          }
          const maxPressure = getNumberValue("max_pressure_psi");
          const maxKn = getNumberValue("max_kn");
          const refDiameter = getNumberValue("ref_diameter_in");

          if (
            !Number.isFinite(totalMass) ||
            totalMass <= 0 ||
            !Number.isFinite(rocketLength) ||
            rocketLength <= 0 ||
            !Number.isFinite(maxPressure) ||
            maxPressure <= 0 ||
            !Number.isFinite(maxKn) ||
            maxKn <= 0 ||
            !Number.isFinite(refDiameter) ||
            refDiameter <= 0
          ) {
            if (status3) status3.textContent = "COMPLETE ALL VEHICLE + CONSTRAINT FIELDS.";
            return;
          }

          const maxStageLengthRatio = 1.15;
          const preferredPropellants = [
            "RCS - Blue Thunder",
            "White Lightning",
            "Black Jack",
            "Green Gorilla",
            "RCS - Warp 9",
            "MIT - Cherry Limeade",
            "MIT - Ocean Water",
            "Skidmark",
            "Redline",
            "AP/Al/HTPB",
            "AP/HTPB",
            "ANCP",
            "APCP",
            "HTPB (hybrid fuel grain)",
            "Composite Propellant",
            "Sugar Propellant",
            "Nakka - KNSB",
            "KNSU",
            "KNDX",
          ];

          const objectives = [
            { name: "apogee_ft" as const, target: apogee, units: "ft" },
            { name: "max_velocity_m_s" as const, target: velocity, units: "m/s" },
          ];

          const payload: MissionTargetPayload = {
            objectives,
            constraints: {
              max_pressure_psi: maxPressure,
              max_kn: maxKn,
              max_vehicle_length_in: rocketLength,
              max_stage_length_ratio: maxStageLengthRatio,
            },
            vehicle: {
              ref_diameter_in: refDiameter,
              rocket_length_in: rocketLength,
              total_mass_lb: totalMass,
            },
            separation_delay_s: separationDelay,
            ignition_delay_s: ignitionDelay,
            allowed_propellants: {
              names: preferredPropellants,
            },
            stage0_length_in: Number.isFinite(stage0Length) ? stage0Length : undefined,
            stage1_length_in:
              stageCount > 1 && Number.isFinite(stage1Length) ? stage1Length : undefined,
          };
          if (Number.isFinite(stage0Length) || Number.isFinite(stage1Length)) {
            payload.solver_config = {
              ...(payload.solver_config || {}),
              stage0_length_in: Number.isFinite(stage0Length) ? stage0Length : undefined,
              stage1_length_in: Number.isFinite(stage1Length) ? stage1Length : undefined,
            };
          }
          const orkPath = window.localStorage.getItem("arx_ork_path");
          if (orkPath) {
            payload.ork_path = orkPath;
          }
          try {
            const launchProfile = window.localStorage.getItem("arx_launch_profile");
            if (launchProfile) {
              const stored = JSON.parse(launchProfile) as Record<string, number>;
              if (Number.isFinite(stored.launch_altitude_ft)) {
                payload.launch_altitude_ft = Number(stored.launch_altitude_ft);
              }
              if (Number.isFinite(stored.rod_length_ft)) {
                payload.rod_length_ft = Number(stored.rod_length_ft);
              }
              if (Number.isFinite(stored.temperature_f)) {
                payload.temperature_f = Number(stored.temperature_f);
              }
              if (Number.isFinite(stored.wind_speed_mph)) {
                payload.wind_speed_mph = Number(stored.wind_speed_mph);
              }
              if (Number.isFinite(stored.launch_angle_deg)) {
                payload.launch_angle_deg = Number(stored.launch_angle_deg);
              }
            }
          } catch (error) {
            console.warn("Invalid arx_cdx1_profile JSON", error);
          }
          try {
            const stored = window.localStorage.getItem("arx_cdx1_profile");
            if (stored) {
              const cdx = JSON.parse(stored) as {
                altitude_ft?: number;
                rod_length_ft?: number;
                temperature_f?: number;
                wind_speed?: number;
                launch_angle_deg?: number;
              };
              if (!Number.isFinite(payload.launch_altitude_ft) && Number.isFinite(cdx.altitude_ft as number)) {
                payload.launch_altitude_ft = Number(cdx.altitude_ft);
              }
              if (!Number.isFinite(payload.rod_length_ft) && Number.isFinite(cdx.rod_length_ft as number)) {
                payload.rod_length_ft = Number(cdx.rod_length_ft);
              }
              if (!Number.isFinite(payload.temperature_f) && Number.isFinite(cdx.temperature_f as number)) {
                payload.temperature_f = Number(cdx.temperature_f);
              }
              if (!Number.isFinite(payload.wind_speed_mph) && Number.isFinite(cdx.wind_speed as number)) {
                payload.wind_speed_mph = Number(cdx.wind_speed);
              }
              if (!Number.isFinite(payload.launch_angle_deg) && Number.isFinite(cdx.launch_angle_deg as number)) {
                payload.launch_angle_deg = Number(cdx.launch_angle_deg);
              }
            }
          } catch (error) {
            console.warn("Invalid arx_cdx1_profile JSON", error);
          }

          if (stageCount === 1 || stageCount === 2) {
            payload.stage_count = stageCount;
          }

          (window as unknown as { ARX_MISSION_TARGET_PAYLOAD?: MissionTargetPayload }).ARX_MISSION_TARGET_PAYLOAD =
            payload;
          window.localStorage.setItem("arx_mission_target_payload", JSON.stringify(payload));

          if (continue3) {
            continue3.disabled = true;
            continue3.style.display = "none";
          }
          startMissionProgress();
          if (resultsSlot) resultsSlot.classList.remove("visible");
          if (status3) status3.textContent = "TARGETS LOCKED. RUNNING OPTIMIZATION.";
          window.addEventListener("arx:mission-target:status", handleMissionStatus as EventListener);
          window.addEventListener("arx:mission-target:error", handleMissionError as EventListener);
          void runMissionTarget();
        });
        back3?.addEventListener("click", () => {
          showStep(2);
        });

        const handleConstraintsInput = (event: Event) => {
          const target = event.target as HTMLElement | null;
          if (!target || !step3 || !step3.contains(target)) return;
          updateConstraintsContinue();
        };
        subPageContent.addEventListener("input", handleConstraintsInput);
        updateConstraintsContinue();
      } else if (type === "ARMOR") {
        const title = "ROCKET DEVELOPMENT";
        document.body.classList.add("holo-active");
        document.body.classList.add("grid-only");
        subPageContent.innerHTML = `
          <div class="subpage-form" data-form="module-r">
            <div class="module-r-page module-r-init" data-page="init">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FLIGHT-READY BUILDER</div>
              <div class="panel-header" style="margin-top: 18px;">IMMUTABLE CONSTRAINT</div>
              <div class="arx-field">
                <input type="number" name="global_width" placeholder=" " min="0" step="any" />
                <label>ROCKET DIAMETER (IN)</label>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="lock-width">Lock Width</button>
              <button type="button" class="arx-btn" data-action="reset-width">Reset</button>
              </div>
            </div>

            <div class="module-r-page module-r-entry" data-page="entry">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FLIGHT-READY BUILDER</div>
              <div class="panel-header" style="margin-top: 18px;">ENTRY PATH</div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="mode-manual">Manual</button>
                <button
                  type="button"
                  class="arx-btn module-r-btn-disabled"
                  data-action="mode-auto"
                  disabled
                  aria-disabled="true"
                >
                  Auto (.ric)
                </button>
              </div>
            <div class="arx-form-actions">
              <button type="button" class="arx-btn" data-action="back-init">Back</button>
            </div>

            <div class="module-r-stage-modal modal-overlay">
              <div class="modal-content">
                <div class="panel-header">AUTO BUILD</div>
                <div class="modal-text">How many stages? (1-5)</div>
                <div class="arx-field">
                  <input type="number" name="stage_count" placeholder=" " min="1" max="5" step="1" />
                  <label>STAGE COUNT</label>
                </div>
                <div class="arx-form-actions">
                  <button type="button" class="arx-btn" data-action="stage-confirm">Confirm</button>
                  <button type="button" class="arx-btn" data-action="stage-cancel">Cancel</button>
                </div>
              </div>
            </div>
            </div>

            <div class="module-r-page module-r-manual" data-page="manual">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FLIGHT-READY BUILDER</div>
              <div class="panel-header" style="margin-top: 18px;">MODULE DASHBOARD</div>
              <div class="grid-container module-r-dashboard">
                <div class="module-card card-square module-r-card" data-card="body">
                  <div class="tech-corner-text tr">BT.01<br/>RDY</div>
                  <div class="tech-corner-text bl">BODY</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">B</span>
                  <span class="card-subtext">BODY TUBES</span>
                  <div class="card-border-bottom"></div>
                </div>
                <div class="module-card card-square module-r-card" data-card="nose">
                  <div class="tech-corner-text tr">NC.02<br/>RDY</div>
                  <div class="tech-corner-text bl">NOSE</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">N</span>
                  <span class="card-subtext">NOSE CONES</span>
                  <div class="card-border-bottom"></div>
                </div>
                <div class="module-card card-square module-r-card" data-card="fins">
                  <div class="tech-corner-text tr">FIN.03<br/>RDY</div>
                  <div class="tech-corner-text bl">FINS</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">F</span>
                  <span class="card-subtext">FIN SETS</span>
                  <div class="card-border-bottom"></div>
                </div>
                <div class="module-card card-square module-r-card" data-card="positioning">
                  <div class="tech-corner-text tr">POS.04<br/>LCK</div>
                  <div class="tech-corner-text bl">STACK</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">P</span>
                  <span class="card-subtext">POSITIONING</span>
                  <div class="card-border-bottom"></div>
                </div>
              </div>
            <div class="arx-form-actions">
              <button type="button" class="arx-btn" data-action="back-entry">Back</button>
            </div>
            </div>

            <div class="module-r-page module-r-body" data-page="body">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">BODY TUBES</div>
              <div class="panel-header" style="margin-top: 18px;">BODY TUBES INDEX</div>
              <div class="form-status">Select a subcomponent.</div>
              <div class="grid-container module-r-subgrid">
                <div class="module-card card-square module-r-card" data-action="open-bulkheads">
                  <div class="tech-corner-text tr">BH.01<br/>RDY</div>
                  <div class="tech-corner-text bl">BULK</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">B</span>
                  <span class="card-subtext">BULKHEADS</span>
                  <div class="card-border-bottom"></div>
                </div>
                <div class="module-card card-square module-r-card" data-action="open-motor-mounts">
                  <div class="tech-corner-text tr">MM.02<br/>RDY</div>
                  <div class="tech-corner-text bl">MOTOR</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">M</span>
                  <span class="card-subtext">MOTOR MOUNTS</span>
                  <div class="card-border-bottom"></div>
                </div>
                <div class="module-card card-square module-r-card" data-action="open-additional-tubes">
                  <div class="tech-corner-text tr">AT.03<br/>RDY</div>
                  <div class="tech-corner-text bl">TUBES</div>
                  <span class="card-label" style="fontSize:3rem;line-height:1;">A</span>
                  <span class="card-subtext">ADDITIONAL TUBES</span>
                  <div class="card-border-bottom"></div>
                </div>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="clear-body">Clear Body Tubes</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-manual">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-bulkheads" data-page="bulkheads">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">BULKHEADS</div>
              <div class="panel-header" style="margin-top: 18px;">BULKHEADS INDEX</div>
              <div class="form-status">How many bulkheads?</div>
              <div class="arx-field">
                <input type="number" name="bulkhead_count" placeholder=" " min="1" max="12" step="1" />
                <label>BULKHEAD COUNT</label>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="bulkheads-next">Continue</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="bulkheads-clear-index">
                  Clear Bulkheads
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-body">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-bulkheads-detail" data-page="bulkheads-detail">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">BULKHEADS</div>
              <div class="panel-header" style="margin-top: 18px;">BULKHEAD DETAILS</div>
              <div class="form-status">Define bulkhead geometry and material per set.</div>
              <div class="module-r-bulkhead-list"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="bulkheads-save">
                  Save Bulkheads
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="bulkheads-clear">
                  Clear Bulkheads
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-bulkheads">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-motor-mounts" data-page="motor-mounts">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">MOTOR MOUNTS</div>
              <div class="panel-header" style="margin-top: 18px;">STAGE CONFIGURATION</div>
              <div class="form-status">How many stages?</div>
              <div class="arx-field">
                <input type="number" name="stage_count_manual" placeholder=" " min="1" max="5" step="1" />
                <label>STAGE COUNT</label>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="motor-mounts-next">Continue</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="motor-mounts-clear-index">
                  Clear Motor Mounts
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-body">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-motor-mounts-detail" data-page="motor-mounts-detail">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">MOTOR MOUNTS</div>
              <div class="panel-header" style="margin-top: 18px;">STAGE DETAILS</div>
              <div class="form-status">Enter stage and inner tube geometry per stage.</div>
              <div class="module-r-stage-list"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="motor-mounts-save">
                  Save Motor Mounts
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="motor-mounts-clear">
                  Clear Motor Mounts
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-motor-mounts">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-additional" data-page="additional-tubes">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">ADDITIONAL TUBES</div>
              <div class="panel-header" style="margin-top: 18px;">ADDITIONAL COMPONENTS</div>
              <div class="form-status">How many additional tubes?</div>
              <div class="arx-field">
                <input type="number" name="additional_tube_count" placeholder=" " min="0" max="10" step="1" />
                <label>ADDITIONAL TUBES</label>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="additional-next">Continue</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="additional-clear-index">
                  Clear Additional Tubes
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-body">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-additional-detail" data-page="additional-detail">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">ADDITIONAL TUBES</div>
              <div class="panel-header" style="margin-top: 18px;">COMPONENT DETAILS</div>
              <div class="form-status">Select component type for each tube.</div>
              <div class="module-r-additional-list"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="additional-save">
                  Save Additional Tubes
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="additional-clear">
                  Clear Additional Tubes
                </button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-additional">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-nose" data-page="nose">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">NOSE CONES</div>
              <div class="panel-header" style="margin-top: 18px;">NOSE CONES INDEX</div>
              <div class="form-status">Enter nose cone geometry and materials.</div>
              <div class="launch-modal-grid">
                <div class="arx-field">
                  <input type="number" name="nose_length_in" placeholder=" " min="0" step="any" />
                  <label>NOSE HEIGHT (IN)</label>
                </div>
                <div class="arx-field">
                  <select name="nose_type">
                    <option value="OGIVE">Ogive</option>
                    <option value="CONICAL">Conical</option>
                    <option value="ELLIPTICAL">Elliptical</option>
                    <option value="PARABOLIC">Parabolic</option>
                  </select>
                </div>
                <div class="arx-field">
                  <select name="nose_material">
                    ${MODULE_R_FULL_MATERIAL_OPTIONS_HTML}
                  </select>
                  <label>NOSE MATERIAL</label>
                </div>
              </div>
              <div class="module-r-nose-preview-grid">
                <div class="module-r-fin-preview-title">NOSE PREVIEW</div>
                <svg class="module-r-fin-preview-svg module-r-nose-preview-svg" data-nose-preview="main" viewBox="0 0 240 130" preserveAspectRatio="xMidYMid meet">
                  <defs>
                    <pattern id="nose-grid" width="12" height="12" patternUnits="userSpaceOnUse">
                      <path d="M 12 0 L 0 0 0 12" fill="none" stroke="rgba(0,243,255,0.25)" stroke-width="1" />
                    </pattern>
                  </defs>
                  <rect x="0" y="0" width="240" height="130" fill="url(#nose-grid)" />
                  <path data-nose-shape="main" d="M 18 110 Q 102 20 220 64 Q 102 108 18 110 Z" fill="rgba(0,243,255,0.24)" stroke="rgba(255,215,0,0.95)" stroke-width="2" />
                </svg>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="save-nose">Save Nose Cone</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="clear-nose">Clear Nose Cone</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-manual">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-fins" data-page="fins">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FIN SETS</div>
              <div class="panel-header" style="margin-top: 18px;">FIN SETS INDEX</div>
              <div class="form-status">How many fin sets?</div>
              <div class="arx-field">
                <input type="number" name="fin_set_count" placeholder=" " min="1" max="8" step="1" />
                <label>FIN SET COUNT</label>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="fins-next">Continue</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="clear-fins-index">Clear Fin Sets</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-manual">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-fins-detail" data-page="fins-detail">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FIN SETS</div>
              <div class="panel-header" style="margin-top: 18px;">FIN SET DETAILS</div>
              <div class="form-status">Select parent tube and fin geometry.</div>
              <div class="module-r-fins-list"></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="fins-save">Save Fin Sets</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="clear-fins">Clear Fin Sets</button>
              </div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="back-fins">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-positioning" data-page="positioning">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">POSITIONING</div>
              <div class="panel-header" style="margin-top: 18px;">POSITIONING INDEX</div>
              <div class="form-status">Drag components into the workspace to set order.</div>
              <div class="module-r-positioning-layout" data-positioning-root></div>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="save-positioning">
                  Save Positioning
                </button>
                <button type="button" class="arx-btn" data-action="back-manual">Back</button>
              </div>
            </div>

            <div class="module-r-page module-r-auto" data-page="auto">
              <div class="form-title">${title}</div>
              <div class="form-subtitle">FLIGHT-READY BUILDER</div>
              <div class="panel-header" style="margin-top: 18px;">AUTO-BUILD (IMPORT .RIC)</div>
              <div class="launch-modal-grid">
                <div class="arx-field">
                  <div class="module-r-file">
                    <span class="module-r-file-name">No file chosen</span>
                    <button type="button" class="arx-btn module-r-file-btn" data-action="pick-ric">
                      Choose File
                    </button>
                    <input type="file" name="ric_file" accept=".ric" multiple />
                  </div>
                </div>
                <div class="arx-field">
                  <input type="number" name="upper_length_m" placeholder=" " min="0" step="any" />
                  <label>UPPER LENGTH (IN)</label>
                </div>
                <div class="arx-field">
                  <input type="number" name="upper_mass_kg" placeholder=" " min="0" step="any" />
                  <label>UPPER MASS (LB)</label>
                </div>
                <div class="arx-field">
                  <input type="number" name="target_apogee_m" placeholder=" " min="0" step="any" />
                  <label>TARGET APOGEE (FT)</label>
                </div>
              </div>
              <div class="arx-form-actions">
                <label class="nav-link" style="display:inline-flex; gap:8px; align-items:center;">
                  <input type="checkbox" name="include_ballast" /> Include Ballast
                </label>
                <label class="nav-link" style="display:inline-flex; gap:8px; align-items:center;">
                  <input type="checkbox" name="include_telemetry" checked /> Include Telemetry
                </label>
                <label class="nav-link" style="display:inline-flex; gap:8px; align-items:center;">
                  <input type="checkbox" name="include_parachute" checked /> Include Parachute
                </label>
              </div>
              <details class="module-r-auto-advanced">
                <summary>Advanced</summary>
                <div class="launch-modal-grid">
                  <div class="arx-field">
                    <input type="number" name="top_n" placeholder=" " min="1" step="1" value="5" />
                    <label>TOP CANDIDATES TO EVALUATE</label>
                  </div>
                  <div class="arx-field">
                    <input type="number" name="random_seed" placeholder=" " step="1" />
                    <label>REPRODUCIBLE SEED (OPTIONAL)</label>
                  </div>
                </div>
              </details>
              <div class="arx-form-actions">
                <button type="button" class="arx-btn" data-action="submit-auto">Submit Auto-Build</button>
              </div>
              <div class="form-status"></div>
              <div class="module-r-auto-results"></div>
            <div class="arx-form-actions">
              <button type="button" class="arx-btn" data-action="back-entry">Back</button>
            </div>
            </div>
          </div>
        `;
        window.setTimeout(() => {
          document.body.classList.remove("grid-only");
          document.body.classList.add("panel-active");
        }, 1000);
      } else if (type === "NETWORK") {
        document.body.classList.add("holo-active");
        document.body.classList.add("grid-only");
        subPageContent.innerHTML = `
          <div class="subpage-form" data-form="coming-soon">
            <div class="form-title">SIMULATIONS</div>
            <div class="form-subtitle">ROCKET SIMULATOR</div>
            <div class="coming-soon-icon"></div>
            <div class="coming-soon-text">COMING SOON</div>
          </div>
        `;
        window.setTimeout(() => {
          document.body.classList.remove("grid-only");
          document.body.classList.add("panel-active");
        }, 1000);
      } else if (type === "PROTO") {
        subPageContent.innerHTML = `
          <form class="subpage-form" data-form="proto" novalidate>
            <div class="form-title">PROTOCOL 8</div>
            <div class="form-subtitle">SECURE CONTACT CHANNEL</div>
            <div class="arx-field">
              <input type="text" name="name" placeholder=" " autocomplete="name" required />
              <label>YOUR NAME</label>
            </div>
            <div class="arx-field">
              <input type="email" name="email" placeholder=" " autocomplete="email" required />
              <label>YOUR EMAIL</label>
            </div>
            <div class="arx-field">
              <textarea name="message" placeholder=" " required></textarea>
              <label>MISSION BRIEF</label>
            </div>
            <div class="form-status"></div>
            <div class="arx-form-actions">
              <button type="submit" class="arx-btn">Transmit</button>
              <button type="button" class="arx-btn" id="proto-clear">Clear</button>
            </div>
          </form>
        `;
      }
      bindFormActions(subPageContent);
      unlockSubPage();
      subPageContent.style.pointerEvents = "auto";
      const interactive = subPageContent.querySelectorAll("input, textarea, button");
      interactive.forEach((el) => {
        (el as HTMLElement).style.pointerEvents = "auto";
      });
    };

    const handleGlobalInput = (isSpaceLike: boolean) => {
      const hint = document.getElementById("spacebar-hint");
      if (isSpaceLike && !hint?.classList.contains("visible")) {
        return;
      }
      const floater = document.getElementById("activeFloater");

      if (pendingSubPageType) {
        revealPendingSubPage();
        return;
      }
      if (!floater) return;

      if (floater.dataset.mode === "mode-x") {
        if (!floater.classList.contains("mode-x-collapsed")) {
          floater.classList.add("mode-x-collapsed");
          floater.classList.remove("centered-massive-word");
          floater.classList.add("centered-contained-word");
          (floater as HTMLElement).style.opacity = "1";
          if (!document.getElementById("activeModuleTitle") && floater.dataset.title) {
            const titleEl = document.createElement("div");
            titleEl.innerText = floater.dataset.title;
            titleEl.className = "module-page-title";
            titleEl.style.color = (floater as HTMLElement).style.color;
            titleEl.id = "activeModuleTitle";
            document.body.appendChild(titleEl);
            requestAnimationFrame(() => {
              titleEl.classList.add("visible");
            });
          }
        }
        return;
      }

      if (floater.classList.contains("centered-massive")) {
        hidePressAnyKey();
        floater.classList.remove("centered-massive");
        floater.classList.add("centered-contained");
        if (floater.dataset.title) {
          const titleEl = document.createElement("div");
          titleEl.innerText = floater.dataset.title;
          titleEl.className = "module-page-title";
          titleEl.style.color = floater.style.color;
          titleEl.id = "activeModuleTitle";
          document.body.appendChild(titleEl);
          requestAnimationFrame(() => {
            titleEl.classList.add("visible");
          });
        }
        setTimeout(() => {
          if (document.getElementById("activeFloater")) {
            document.getElementById("spacebar-hint")?.classList.add("visible");
          }
        }, 1200);
      } else if (floater.classList.contains("centered-contained") && isSpaceLike) {
        document.getElementById("spacebar-hint")?.classList.remove("visible");
        initiateArcSequence(floater);
      } else if (floater.classList.contains("centered-massive-word")) {
        hidePressAnyKey();
        floater.classList.remove("centered-massive-word");
        floater.classList.add("centered-contained-word");
        if (floater.dataset.title) {
          const titleEl = document.createElement("div");
          titleEl.innerText = floater.dataset.title;
          titleEl.className = "module-page-title";
          titleEl.style.color = floater.style.color;
          titleEl.id = "activeModuleTitle";
          document.body.appendChild(titleEl);
          requestAnimationFrame(() => {
            titleEl.classList.add("visible");
          });
        }
      }
    };

    document.addEventListener("keydown", (e) => {
      if (e.code === "Space") {
        e.preventDefault();
        handleGlobalInput(true);
        return;
      }
      handleGlobalInput(false);
    });

    document.addEventListener(
      "pointerdown",
      (event) => {
        const target = event.target as HTMLElement | null;
        if (
          target?.closest(
            "input, textarea, button, .dob-calendar, .dropdown-menu, #holo-container"
          )
        ) {
          return;
        }
        handleGlobalInput(true);
      },
      true
    );

    const launchBtn = document.getElementById("launchSettingsBtn");
    launchBtn?.addEventListener("click", (event) => {
      event.preventDefault();
      openLaunchModal();
    });
    const launchModal = document.getElementById("launchModal");
    const launchBackdrop = document.getElementById("launchModalBackdrop");
    const launchSave = document.getElementById("launchModalSave");
    const launchClose = document.getElementById("launchModalClose");
    launchBackdrop?.addEventListener("click", closeLaunchModal);
    launchClose?.addEventListener("click", closeLaunchModal);
    launchSave?.addEventListener("click", () => {
      if (!launchModal) return;
      const inputs = getLaunchInputs(launchModal);
      const profile: Record<string, number> = {};
      const setIfFinite = (key: string, input: HTMLInputElement | null) => {
        if (!input) return;
        const value = Number(input.value);
        if (Number.isFinite(value)) profile[key] = value;
      };
      setIfFinite("launch_altitude_ft", inputs.altitude);
      setIfFinite("temperature_f", inputs.temperature);
      setIfFinite("wind_speed_mph", inputs.wind);
      setIfFinite("rod_length_ft", inputs.rodLength);
      setIfFinite("launch_angle_deg", inputs.angle);
      saveLaunchProfile(profile);
      closeLaunchModal();
    });

    const resetDashboard = () => {
      document.documentElement.style.setProperty("--grid-color", "0, 243, 255");
      document.getElementById("blackout-screen")?.classList.remove("active");
      const loginLayer = document.getElementById("login-layer");
      if (loginLayer) loginLayer.innerHTML = "";
      const successLayer = document.getElementById("success-layer");
      if (successLayer) successLayer.innerHTML = "";
      document.getElementById("backBtnContainer")?.classList.remove("hidden-fast");
      document.getElementById("arc-reactor-overlay")?.classList.remove("active");
      document.getElementById("arc-reactor-overlay")?.classList.remove("arc-reactor-corner");
      document.body.classList.remove("grid-mat-active");
      document.body.classList.remove("holo-active");
      document.getElementById("ring1")?.classList.remove("hidden-fast");
      document.getElementById("ring2")?.classList.remove("hidden-fast");
      document.querySelector(".close-x-btn")?.classList.remove("active");
      document.getElementById("spacebar-hint")?.classList.remove("visible");
      hidePressAnyKey();
      document.getElementById("subPage")?.classList.remove("active");
      document.getElementById("subPage")?.classList.remove("locked");
      document.getElementById("subPage")?.classList.remove("form-active");
      document
        .getElementById("arc-reactor-overlay")
        ?.classList.remove("active", "form-mode");
      const subPageContent = document.getElementById("subPageContent");
      if (subPageContent) subPageContent.innerHTML = "";
      if (telemetryGraph) {
        telemetryGraph.dispose();
        telemetryGraph = null;
      }
      isSubPageLocked = false;
      pendingSubPageType = null;
      const floaters = document.querySelectorAll(".floating-letter");
      floaters.forEach((f) => {
        (f as HTMLElement).style.opacity = "0";
        setTimeout(() => f.remove(), 500);
      });
      const titleEl = document.getElementById("activeModuleTitle");
      if (titleEl) {
        titleEl.style.opacity = "0";
        setTimeout(() => titleEl.remove(), 500);
      }
      document.getElementById("topNav")?.classList.remove("fade-exit");
      document.querySelectorAll(".side-panel").forEach((el) => el.classList.remove("fade-exit"));
      document.getElementById("moduleGrid")?.classList.remove("fade-exit");
      updateAuthUI();

      const ring1 = document.getElementById("ring1");
      const ring2 = document.getElementById("ring2");
      if (ring1) ring1.className = "reactor-ring";
      if (ring2) ring2.className = "reactor-ring-inner";
      ring1?.classList.remove(
        "ring-teal",
        "ring-gold",
        "ring-green",
        "ring-yellow",
        "ring-white",
        "ring-red",
        "ring-purple"
      );
      ring2?.classList.remove(
        "ring-teal-inner",
        "ring-gold-inner",
        "ring-green-inner",
        "ring-yellow-inner",
        "ring-white-inner",
        "ring-red-inner",
        "ring-purple-inner"
      );

      randomizeDashboardData();

      setTimeout(() => {
        isTransitioning = false;
        updateRocketSize();
      }, 500);
    };

    const closeModal = () => {
      const modal = document.getElementById("modeXModal");
      if (modal) modal.style.display = "none";
    };

    const confirmModeX = () => {
      closeModal();
      document.documentElement.style.setProperty("--grid-color", "255, 51, 51");
      if (voiceAudio) {
        voiceAudio.pause();
        voiceAudio.currentTime = 0;
      }
      if (bgmAudio) {
        bgmAudio.pause();
        bgmAudio.currentTime = 0;
      }
      alarmAudio = new Audio(
        "https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/alarm-301729.mp3"
      );
      alarmAudio.loop = true;
      alarmAudio.volume = 0.7;
      alarmAudio.play().catch(() => {});

      document.getElementById("modeXSkipBtn")?.classList.add("visible");
      const modeXCard = document.getElementById("modeXBtn");
      const ring1 = document.getElementById("ring1");
      const ring2 = document.getElementById("ring2");

      document.querySelectorAll(".side-panel").forEach((el) => el.classList.add("fade-exit"));
      document.getElementById("topNav")?.classList.add("fade-exit");
      document
        .querySelectorAll(".module-card")
        .forEach((el) => el.id !== "modeXBtn" && el.classList.add("fade-exit"));
      modeXCard?.classList.add("mode-x-center");

      modeXTimeouts.push(
        window.setTimeout(() => {
          ring1?.classList.add("reactor-critical");
          ring2?.classList.add("reactor-critical");
          modeXTimeouts.push(
            window.setTimeout(() => {
              modeXCard?.classList.add("shake-hard");
              modeXTimeouts.push(
                window.setTimeout(() => {
                  modeXCard?.classList.add("vanish-final");
                  if (alarmAudio) {
                    alarmAudio.pause();
                    alarmAudio.currentTime = 0;
                  }
                  document.getElementById("modeXSkipBtn")?.classList.remove("visible");
                  ring1?.classList.remove("reactor-critical", "vanish-final");
                  ring2?.classList.remove("reactor-critical", "vanish-final");
                  ring1?.classList.add("ring-red");
                  ring2?.classList.add("ring-red-inner");
                  const staleSpinner = document.getElementById("modeXBufferIcon");
                  if (staleSpinner) staleSpinner.remove();
                  const floater = document.createElement("span");
                  floater.innerText = "COMING SOON";
                  floater.dataset.title = "A.R.X";
                  floater.dataset.mode = "mode-x";
                  floater.className = "floating-letter centered-massive-word";
                  floater.style.color = "#ff3333";
                  floater.style.fontSize = "2.4rem";
                  floater.id = "activeFloater";
                  document.body.appendChild(floater);
                  const spinner = document.createElement("div");
                  spinner.className = "coming-soon-icon mode-x-buffer-icon";
                  spinner.id = "modeXBufferIcon";
                  document.body.appendChild(spinner);
                  document.body.classList.remove("grid-only");
                  document.body.classList.add("panel-active");
                  const subPageBtn = document.getElementById(
                    "subPageBtn"
                  ) as HTMLButtonElement | null;
                  if (subPageBtn) {
                    subPageBtn.innerText = "TURN OFF MODE X";
                    subPageBtn.onclick = turnOffModeX;
                  }
                  document.getElementById("subPage")?.classList.add("active");
                  document.body.style.backgroundColor = "#000";
                }, 1500)
              );
            }, 1500)
          );
        }, 1000)
      );
    };

    const skipModeXAnimation = () => {
      modeXTimeouts.forEach((id) => clearTimeout(id));
      modeXTimeouts = [];
      if (alarmAudio) {
        alarmAudio.pause();
        alarmAudio.currentTime = 0;
      }
      document.getElementById("modeXSkipBtn")?.classList.remove("visible");
      const modeXCard = document.getElementById("modeXBtn");
      const ring1 = document.getElementById("ring1");
      const ring2 = document.getElementById("ring2");
      modeXCard?.classList.add("vanish-final", "mode-x-center");
      ring1?.classList.remove("reactor-critical");
      ring2?.classList.remove("reactor-critical");
      ring1?.classList.add("ring-red");
      ring2?.classList.add("ring-red-inner");
      const staleSpinner = document.getElementById("modeXBufferIcon");
      if (staleSpinner) staleSpinner.remove();
      const floater = document.createElement("span");
      floater.innerText = "COMING SOON";
      floater.dataset.title = "A.R.X";
      floater.dataset.mode = "mode-x";
      floater.className = "floating-letter centered-massive-word";
      floater.style.color = "#ff3333";
      floater.style.fontSize = "2.4rem";
      floater.id = "activeFloater";
      document.body.appendChild(floater);
      const spinner = document.createElement("div");
      spinner.className = "coming-soon-icon mode-x-buffer-icon";
      spinner.id = "modeXBufferIcon";
      document.body.appendChild(spinner);
      const subPageBtn = document.getElementById("subPageBtn") as HTMLButtonElement | null;
      if (subPageBtn) {
        subPageBtn.innerText = "TURN OFF MODE X";
        subPageBtn.onclick = turnOffModeX;
      }
      document.body.classList.remove("grid-only");
      document.body.classList.add("panel-active");
      document.getElementById("subPage")?.classList.add("active");
      document.body.style.backgroundColor = "#000";
    };

    const turnOffModeX = () => {
      document.getElementById("modeXBufferIcon")?.remove();
      const floater = document.getElementById("activeFloater");
      if (floater) {
        floater.classList.remove("centered-massive-word", "text-fade-visible");
        floater.classList.add("implode-into-core");
        setTimeout(() => {
          floater.remove();
          document.querySelectorAll(".floating-letter").forEach((node) => {
            const text = node.textContent?.trim();
            if (text === "MODE X" || text === "COMING SOON") {
              node.remove();
            }
          });
        }, 3000);
      }
      const titleEl = document.getElementById("activeModuleTitle");
      if (titleEl) {
        titleEl.style.opacity = "0";
        setTimeout(() => titleEl.remove(), 2000);
      }
      document.getElementById("subPage")?.classList.remove("active");
      setTimeout(() => {
        const ring1 = document.getElementById("ring1");
        const ring2 = document.getElementById("ring2");
        ring1?.classList.remove("ring-red");
        ring2?.classList.remove("ring-red-inner");
        setTimeout(() => {
          const topNav = document.getElementById("topNav");
          topNav?.classList.add("boot-hidden");
          document.querySelectorAll(".side-panel").forEach((p) => p.classList.add("boot-hidden"));
          document.querySelectorAll(".module-card").forEach((c) => {
            c.classList.remove("fade-exit", "vanish-final", "mode-x-center", "shake-hard");
            c.classList.add("boot-scale-hidden");
            if (c.id === "modeXBtn") (c as HTMLElement).style.cssText = "";
          });
          topNav?.classList.remove("fade-exit");
          document.querySelectorAll(".side-panel").forEach((p) => p.classList.remove("fade-exit"));
          setTimeout(() => {
            topNav?.classList.remove("boot-hidden");
            topNav?.classList.add("boot-visible");
          }, 500);
          setTimeout(() => {
            document.querySelectorAll(".side-panel").forEach((p) => {
              p.classList.remove("boot-hidden");
              p.classList.add("boot-visible");
            });
            updateRocketSize();
          }, 1000);
          const cards = document.querySelectorAll(".module-card");
          cards.forEach((card, index) => {
            setTimeout(() => {
              card.classList.remove("boot-scale-hidden");
              card.classList.add("boot-scale-visible");
            }, 1500 + index * 200);
          });
          setTimeout(() => {
            isTransitioning = false;
          }, 2000);
        }, 2000);
      }, 2500);
    };

    // Bind handlers
    const moduleButtons = document.querySelectorAll(".module-card");
    moduleButtons.forEach((card) => {
      card.addEventListener("click", () => selectModule(card.id === "modeXBtn" ? "ADVANCED" : card.id.replace("card-", ""), card as HTMLElement));
    });
    document.querySelectorAll("[data-action]").forEach((el) => {
      el.addEventListener("click", () =>
        handleNavClick((el as HTMLElement).dataset.action || "")
      );
    });

    const closeX = document.querySelector(".close-x-btn");
    closeX?.addEventListener("click", closeArcSequence);
    const btnYes = document.getElementById("btn-yes");
    const btnNo = document.getElementById("btn-no");
    btnYes?.addEventListener("click", confirmModeX);
    btnNo?.addEventListener("click", closeModal);
    const modeXSkipBtn = document.getElementById("modeXSkipBtn");
    modeXSkipBtn?.addEventListener("click", skipModeXAnimation);

    const subPageContainer = document.getElementById("subPage");
    subPageContainer?.addEventListener("click", () => {
      if (pendingSubPageType) {
        revealPendingSubPage();
      }
    });

    document.addEventListener(
      "click",
      (event) => {
        if (pendingSubPageType) {
          revealPendingSubPage();
        }
      },
      true
    );

    // STARSHIP HOLOGRAM 3D ENGINE
    const rocketCanvasEl = document.getElementById("rocketCanvas") as HTMLCanvasElement | null;
    const holoContainer = document.getElementById("holo-container");
    const rocketCtx = rocketCanvasEl?.getContext("2d") || null;
    const rocketDpr = window.devicePixelRatio || 1;

    let rocketVertices: Array<{ x: number; y: number; z: number }> = [];
    let rocketEdges: Array<[number, number]> = [];
    const ROCKET_COLOR = "#00f3ff";
    const ROCKET_COLOR_DIM = "rgba(0, 243, 255, 0.15)";
    const ROCKET_ROTATION_SPEED = 0.01;

    class Point3D {
      constructor(public x: number, public y: number, public z: number) {}
    }

    const createRocketRing = (y: number, radius: number, segments: number) => {
      const startIdx = rocketVertices.length;
      for (let i = 0; i < segments; i++) {
        const theta = (i / segments) * Math.PI * 2;
        const x = Math.cos(theta) * radius;
        const z = Math.sin(theta) * radius;
        rocketVertices.push(new Point3D(x, y, z));
      }
      for (let i = 0; i < segments; i++) {
        rocketEdges.push([startIdx + i, startIdx + ((i + 1) % segments)]);
      }
      return startIdx;
    };

    const addRocketFlap = (yBottom: number, yTop: number, radius: number, reach: number, angleOffset: number) => {
      const x1 = Math.cos(angleOffset) * radius;
      const z1 = Math.sin(angleOffset) * radius;
      const x2 = Math.cos(angleOffset) * (radius * reach);
      const z2 = Math.sin(angleOffset) * (radius * reach);
      const p1 = new Point3D(x1, yBottom, z1);
      const p2 = new Point3D(x2, yBottom - 10, z2);
      const p3 = new Point3D(x2, yTop + 10, z2);
      const p4 = new Point3D(x1, yTop, z1);
      const idx = rocketVertices.length;
      rocketVertices.push(p1, p2, p3, p4);
      rocketEdges.push([idx, idx + 1]);
      rocketEdges.push([idx + 1, idx + 2]);
      rocketEdges.push([idx + 2, idx + 3]);
      rocketEdges.push([idx + 3, idx]);
      rocketEdges.push([idx, idx + 2]);
    };

    const addRocketEngine = (xOffset: number, zOffset: number, y: number, size: number) => {
      const tip = new Point3D(xOffset, y + 20, zOffset);
      const idx = rocketVertices.push(tip) - 1;
      const ringBase = createRocketRing(y, size, 8);
      for (let i = 0; i < 8; i++) {
        rocketVertices[ringBase + i].x += xOffset;
        rocketVertices[ringBase + i].z += zOffset;
        rocketEdges.push([idx, ringBase + i]);
      }
    };

    const initRocketModel = () => {
      rocketVertices = [];
      rocketEdges = [];
      const SEGMENTS = 16;
      const R = 40;
      const b1 = createRocketRing(200, R, SEGMENTS);
      const b2 = createRocketRing(150, R, SEGMENTS);
      const b3 = createRocketRing(50, R, SEGMENTS);
      const b4 = createRocketRing(-40, R, SEGMENTS);
      for (let i = 0; i < SEGMENTS; i++) {
        rocketEdges.push([b1 + i, b4 + i]);
      }
      [0, 4, 8, 12].forEach((idx) => {
        const p = rocketVertices[b4 + idx];
        const finTip = new Point3D(p.x * 1.4, p.y, p.z * 1.4);
        const finIdx = rocketVertices.push(finTip) - 1;
        rocketEdges.push([b4 + idx, finIdx]);
        rocketEdges.push([b3 + idx, finIdx]);
      });
      const s1 = b4;
      const s2 = createRocketRing(-100, R, SEGMENTS);
      const s3 = createRocketRing(-160, R * 0.7, SEGMENTS);
      const s4 = createRocketRing(-190, 0, SEGMENTS);
      for (let i = 0; i < SEGMENTS; i++) {
        rocketEdges.push([s1 + i, s2 + i]);
        rocketEdges.push([s2 + i, s3 + i]);
        rocketEdges.push([s3 + i, s4 + i]);
      }
      addRocketFlap(-50, -90, R, 1.8, 0);
      addRocketFlap(-50, -90, R, 1.8, Math.PI);
      addRocketFlap(-130, -150, R, 1.5, 0);
      addRocketFlap(-130, -150, R, 1.5, Math.PI);
      addRocketEngine(0, 0, 200, 10);
      addRocketEngine(15, 0, 200, 8);
      addRocketEngine(-15, 0, 200, 8);
    };

    let rocketAngle = 0;
    let rocketAnimationId: number | null = null;
    let holoZoom = 1;

    const applyHoloTransform = () => {
      if (!holoContainer) return;
      holoContainer.style.transform = `scale(${holoZoom})`;
    };

    const updateRocketSize = () => {
      if (!rocketCanvasEl || !rocketCtx || !holoContainer) return;
      const rect = holoContainer.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      rocketCanvasEl.width = rect.width * rocketDpr;
      rocketCanvasEl.height = rect.height * rocketDpr;
      rocketCtx.setTransform(rocketDpr, 0, 0, rocketDpr, 0, 0);
    };

    const resizeObserver =
      holoContainer && "ResizeObserver" in window
        ? new ResizeObserver(() => updateRocketSize())
        : null;
    if (resizeObserver && holoContainer) resizeObserver.observe(holoContainer);

    const renderRocket = () => {
      if (!rocketCanvasEl || !rocketCtx || !holoContainer) return;
      const w = rocketCanvasEl.width / rocketDpr;
      const h = rocketCanvasEl.height / rocketDpr;
      if (w === 0 || h === 0) {
        rocketAnimationId = requestAnimationFrame(renderRocket);
        return;
      }
      rocketCtx.clearRect(0, 0, w, h);
      const cx = w / 2;
      const cy = h / 2;
      const globalScale = Math.min(w, h) * 0.0035 * 2.1;
      rocketAngle += ROCKET_ROTATION_SPEED;
      const sin = Math.sin(rocketAngle);
      const cos = Math.cos(rocketAngle);
      rocketCtx.lineWidth = 2;
      rocketCtx.lineJoin = "round";
      const projected = rocketVertices.map((v) => {
        const x = v.x * cos - v.z * sin;
        const z = v.x * sin + v.z * cos;
        const scale = (1000 / (1000 + z)) * globalScale;
        return { x: cx + x * scale, y: cy + v.y * scale, z };
      });
      rocketEdges.forEach((edge) => {
        const p1 = projected[edge[0]];
        const p2 = projected[edge[1]];
        const isBack = p1.z < 0 && p2.z < 0;
        rocketCtx.beginPath();
        rocketCtx.moveTo(p1.x, p1.y);
        rocketCtx.lineTo(p2.x, p2.y);
        rocketCtx.strokeStyle = isBack ? ROCKET_COLOR_DIM : ROCKET_COLOR;
        rocketCtx.stroke();
      });
      rocketAnimationId = requestAnimationFrame(renderRocket);
    };

    initRocketModel();
    renderRocket();
    applyHoloTransform();

    if (holoContainer) {
      holoContainer.addEventListener("wheel", (event) => {
        event.preventDefault();
        const delta = event.deltaY > 0 ? -0.06 : 0.06;
        holoZoom = Math.max(0.6, Math.min(1.6, holoZoom + delta));
        applyHoloTransform();
      });
    }

    return () => {
      window.removeEventListener("resize", resize);
      if (animationId) cancelAnimationFrame(animationId);
      if (rocketAnimationId) cancelAnimationFrame(rocketAnimationId);
      if (warpInterval) clearInterval(warpInterval);
      if (resizeObserver) resizeObserver.disconnect();
      if (engineAnimationId) cancelAnimationFrame(engineAnimationId);
      if (engineResizeObserver) engineResizeObserver.disconnect();
      if (engineControls) engineControls.dispose();
      if (engineComposer) engineComposer.dispose();
      if (engineRenderer) {
        engineRenderer.dispose();
        const dom = engineRenderer.domElement;
        dom?.parentElement?.removeChild(dom);
      }
      bootTimeouts.forEach((id) => clearTimeout(id));
      modeXTimeouts.forEach((id) => clearTimeout(id));
      landingAudio.pause();
      window.removeEventListener("pointerdown", startLandingAudio);
      btn?.removeEventListener("click", startClick);
      skipBtn?.removeEventListener("click", skipIntro);
    };
  }, []);

  return (
    <>
      <div id="arc-reactor-overlay">
        <div className="arc-ring arc-r1"></div>
        <div className="arc-ring arc-r2"></div>
        <div className="arc-ring arc-r3"></div>
        <div className="arc-core"></div>
      </div>
      <div id="grid-mat-layer" aria-hidden="true">
        <div id="grid-mat"></div>
        <div id="holo-layer" aria-hidden="true">
          <svg className="holo-arc" viewBox="0 0 360 160" preserveAspectRatio="none">
            <path
              d="M10 140 Q180 10 350 140"
              fill="none"
              stroke="rgba(0, 243, 255, 0.45)"
              strokeWidth="2"
            />
          </svg>
        </div>
      </div>
      <div id="holo-side-layer" aria-hidden="true"></div>
      <div id="telemetry-graph-layer" aria-hidden="true">
        <div id="telemetry-graph-left" role="img" aria-label="Telemetry graph"></div>
      </div>
      <div id="holo-orbit-layer" aria-hidden="true">
      </div>
      <div id="login-layer"></div>
      <div id="success-layer"></div>
      <div id="blackout-screen"></div>
      <div className="close-x-btn"></div>
      <div id="spacebar-hint">PRESS SPACEBAR TO INITIALIZE</div>
      <div id="press-any-key-layer">
        <div id="press-any-key-text">PRESS ANY KEY</div>
      </div>

      <div id="landing-container">
        <div id="background">
          <div className="nebula"></div>
        </div>
        <canvas id="stars"></canvas>
        <section className="hero" id="hero-section">
          <div className="logo-container">
            <div className="logo">
              <img
                src="https://raw.githubusercontent.com/mehul422/ArX/main/frontend/public/main.png"
                alt="ARX Logo"
              />
            </div>
          </div>
          <h1>ARX</h1>
          <p>AUTOMATED ROCKET EXPLORATION</p>
          <button className="btn" id="start-btn">
            GET STARTED
          </button>
        </section>
      </div>

      <button id="skip-btn">SKIP INTRO</button>
      <button id="modeXSkipBtn">SKIP WARNING</button>
      <div id="warp-flash"></div>
      <div id="boot-text">WELCOME, BOSS</div>

      <div id="dashboard-container">
        <div id="modeXModal" className="modal-overlay">
          <div className="modal-content">
            <div
              className="panel-header"
              style={{ color: "#ff3333", borderColor: "#ff3333", marginBottom: 20 }}
            >
              SYSTEM OVERRIDE
            </div>
            <div className="modal-text">
              This mode does all three tasks of A.R.X. together.
              <br />
              Do you want to continue?
            </div>
            <div style={{ display: "flex", justifyContent: "center", gap: 20 }}>
              <button className="nav-link accent" id="btn-yes">
                YES
              </button>
              <button className="nav-link" id="btn-no">
                NO
              </button>
            </div>
          </div>
        </div>

        <div id="subPage" className="sub-page-container">
          <div id="subPageContent"></div>
          <div className="back-btn-container" id="backBtnContainer">
            <button className="nav-link" id="subPageBtn">
              RETURN TO DASHBOARD
            </button>
          </div>
        </div>

        <div className="reactor-ring" id="ring1"></div>
        <div className="reactor-ring-inner" id="ring2"></div>

        <nav className="top-nav boot-hidden" id="topNav">
          <div className="nav-left profile-container">
            <div className="profile-bubble">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#00f3ff"
                strokeWidth="2"
              >
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
            </div>
            <div className="dropdown-menu">
              <div className="dropdown-item" data-action="INIT">
                LOG IN
              </div>
              <div className="dropdown-item" data-action="PRICING">
                PRICING
              </div>
              <div className="dropdown-item" data-action="PROTO">
                CONTACT US
              </div>
            </div>
          </div>
          <div className="nav-right">
            <button className="nav-link launch-settings-btn" id="launchSettingsBtn" title="Launch parameters">
              LAUNCH
            </button>
            <button className="nav-link" data-action="INIT">
              Initialize
            </button>
            <button className="nav-link" data-action="NEW">
              New User
            </button>
            <button className="nav-link accent" data-action="PROTO">
              Protocol 8
            </button>
          </div>
        </nav>

        <div className="launch-modal" id="launchModal" aria-hidden="true">
          <div className="launch-modal-backdrop" id="launchModalBackdrop"></div>
          <div className="launch-modal-panel" role="dialog" aria-modal="true">
            <div className="launch-modal-title">LAUNCH PARAMETERS</div>
            <div className="launch-modal-subtitle">Set once for all runs</div>
            <div className="launch-modal-grid">
              <div className="arx-field">
                <input type="number" name="launch_altitude_ft" placeholder=" " min="0" step="any" />
                <label>LAUNCH SITE ELEVATION (FT)</label>
              </div>
              <div className="arx-field">
                <input type="number" name="temperature_f" placeholder=" " step="any" />
                <label>TEMPERATURE (F)</label>
              </div>
              <div className="arx-field">
                <input type="number" name="wind_speed_mph" placeholder=" " min="0" step="any" />
                <label>WIND SPEED (MPH)</label>
              </div>
              <div className="arx-field">
                <input type="number" name="rod_length_ft" placeholder=" " min="0" step="any" />
                <label>LAUNCH RAIL LENGTH (FT)</label>
              </div>
              <div className="arx-field">
                <input type="number" name="launch_angle_deg" placeholder=" " step="any" />
                <label>LAUNCH ANGLE (DEG)</label>
              </div>
            </div>
            <div className="launch-modal-actions">
              <button type="button" className="arx-btn" id="launchModalSave">Save</button>
              <button type="button" className="arx-btn" id="launchModalClose">Close</button>
            </div>
          </div>
        </div>

        <main className="main-stage">
          <div className="hud-panel side-panel boot-hidden">
            <div className="panel-header">ARX-E1 ENGINE OUTPUT</div>
            <div className="graph-container">
              <svg width="100%" height="100%" viewBox="0 0 300 200" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style={{ stopColor: "rgba(255,157,0,0)", stopOpacity: 1 }} />
                    <stop offset="100%" style={{ stopColor: "rgba(255,157,0,1)", stopOpacity: 1 }} />
                  </linearGradient>
                </defs>
                <path
                  className="thrust-line"
                  d="M0,180 Q30,170 50,150 T100,100 T150,120 T200,60 T250,80 T300,20"
                  stroke="url(#grad1)"
                  strokeDasharray="5,5"
                />
                <line x1="0" y1="50" x2="300" y2="50" stroke="rgba(0,243,255,0.1)" strokeWidth="1" />
                <line x1="0" y1="100" x2="300" y2="100" stroke="rgba(0,243,255,0.1)" strokeWidth="1" />
                <line x1="0" y1="150" x2="300" y2="150" stroke="rgba(0,243,255,0.1)" strokeWidth="1" />
              </svg>
            </div>
            <div style={{ fontSize: "0.7rem", color: "var(--cyan-dim)", marginTop: 5 }}>
              &gt; CHAMBER PRESSURE: <span id="val-pressure">300</span> BAR
              <br />
              &gt; LOX LEVEL: <span id="val-lox">92%</span>
              <br />
              &gt; CH4 LEVEL: <span id="val-ch4">94%</span>
            </div>
          </div>

          <div className="center-stage">
            <div className="grid-container" id="moduleGrid">
              <div className="module-card card-square boot-scale-hidden" id="card-SYSTEM">
                <div className="tech-corner-text tr">
                  SYS.64
                  <br />
                  ACT
                </div>
                <div className="tech-corner-text bl" id="val-sys">
                  45.211
                </div>
                <span className="card-label" style={{ fontSize: "3rem", lineHeight: 1 }}>
                  A
                </span>
                <span className="card-subtext">MOTOR DEVELOPMENT</span>
                <div className="card-border-bottom"></div>
              </div>
              <div className="module-card card-square boot-scale-hidden" id="card-ARMOR">
                <div className="tech-corner-text tr">
                  MK.85
                  <br />
                  RDY
                </div>
                <div className="tech-corner-text bl" id="val-arm">
                  98.4%
                </div>
                <span className="card-label" style={{ fontSize: "3rem", lineHeight: 1 }}>
                  R
                </span>
                <span className="card-subtext">ROCKET DEVELOPMENT</span>
                <div className="card-border-bottom"></div>
              </div>
              <div className="module-card card-square boot-scale-hidden" id="card-NETWORK">
                <div className="tech-corner-text tr">
                  NET.09
                  <br />
                  UPL
                </div>
                <div className="tech-corner-text bl" id="val-net">
                  120 TB/s
                </div>
                <span className="card-label" style={{ fontSize: "3rem", lineHeight: 1 }}>
                  X
                </span>
                <span className="card-subtext">SIMULATIONS</span>
                <div className="card-border-bottom"></div>
              </div>
              <div className="module-card card-wide red-alert boot-scale-hidden" id="modeXBtn">
                <div className="tech-corner-text tr">
                  ADV.OP
                  <br />
                  SECURE
                </div>
                <div className="tech-corner-text bl" id="val-modex">
                  LAT: 34.05 LON: -118.25
                </div>
                <span className="card-label">MODE X</span>
                <span
                  className="card-subtext"
                  style={{
                    color: "#ff4d4d",
                    textShadow: "0 0 15px #ff0000, 0 0 5px #ff0000",
                    opacity: 1,
                    fontWeight: "bold",
                  }}
                >
                  THREAT LEVEL: HIGH
                </span>
                <div className="card-border-bottom"></div>
              </div>
            </div>
          </div>

          <div className="hud-panel side-panel boot-hidden">
            <div className="panel-header">ARX-V1 TELEMETRY</div>
            <div id="holo-container">
              <div className="scan-line"></div>
              <div className="scanner-bar"></div>
              <div className="hologram-flicker"></div>
              <canvas id="rocketCanvas"></canvas>
            </div>
            <div style={{ fontSize: "0.7rem", color: "var(--cyan-dim)", textAlign: "right" }}>
              SCANNING HULL...
              <br />
              TILES: 100% SECURE
              <br />
              PAYLOAD: DEPLOYED
            </div>
          </div>
        </main>
      </div>
    </>
  );
};

export default ArxInterface;