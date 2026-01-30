import React, { useEffect } from "react";
import "./ArxInterface.css";

const ArxInterface: React.FC = () => {
  useEffect(() => {
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
    let hasBooted = false;
    let isTransitioning = false;
    let activeModuleId: string | null = null;
    let isSubPageLocked = false;
    let pendingSubPageType: string | null = null;

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
    let enableAudio: (() => void) | null = null;
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
        }, 4000);
      }
    };

    const closeArcSequence = () => {
      document.getElementById("arc-reactor-overlay")?.classList.remove("active");
      document.getElementById("arc-reactor-overlay")?.classList.remove("arc-reactor-corner");
      document.body.classList.remove("grid-mat-active");
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
          subPageContent.innerHTML =
            '<div class="pricing-grid"><div class="pricing-box"></div><div class="pricing-box"></div><div class="pricing-box"></div></div>';
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
          const dobDate = new Date(Number(year), Number(month) - 1, Number(day));
          if (Number.isNaN(dobDate.getTime())) {
            clearAgeTimer();
            labelEl.textContent = "DATE OF BIRTH";
            ageEl.textContent = "";
            fieldEl.classList.remove("age-active");
            return;
          }
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
          const dob = readDobValue();
          if (!name || !email || !dob) {
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
          const hasDob = hasAnyDobInput();
          if (!name && !email && !hasDob) {
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
      pendingSubPageType = type;
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

    document.addEventListener("keydown", (e) => {
      const hint = document.getElementById("spacebar-hint");
      if (e.code === "Space" && !hint?.classList.contains("visible")) {
        return;
      }
      const floater = document.getElementById("activeFloater");

      if (pendingSubPageType) {
        revealPendingSubPage();
        return;
      }
      if (!floater) return;

      if (floater.dataset.mode === "mode-x") {
        e.preventDefault();
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
      } else if (floater.classList.contains("centered-contained") && e.code === "Space") {
        e.preventDefault();
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
                  const floater = document.createElement("span");
                  floater.innerText = "MODE X";
                  floater.dataset.title = "A.R.X";
                  floater.dataset.mode = "mode-x";
                  floater.className = "floating-letter centered-massive-word text-fade-entry";
                  floater.style.color = "#ff3333";
                  floater.style.fontSize = "4rem";
                  floater.id = "activeFloater";
                  document.body.appendChild(floater);
                  requestAnimationFrame(() => {
                    setTimeout(() => {
                      floater.classList.add("text-fade-visible");
                    }, 50);
                  });
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
      const floater = document.createElement("span");
      floater.innerText = "MODE X";
      floater.dataset.title = "A.R.X";
      floater.dataset.mode = "mode-x";
      floater.className =
        "floating-letter centered-massive-word text-fade-entry text-fade-visible";
      floater.style.color = "#ff3333";
      floater.style.fontSize = "4rem";
      floater.id = "activeFloater";
      document.body.appendChild(floater);
      const subPageBtn = document.getElementById("subPageBtn") as HTMLButtonElement | null;
      if (subPageBtn) {
        subPageBtn.innerText = "TURN OFF MODE X";
        subPageBtn.onclick = turnOffModeX;
      }
      document.getElementById("subPage")?.classList.add("active");
      document.body.style.backgroundColor = "#000";
    };

    const turnOffModeX = () => {
      const floater = document.getElementById("activeFloater");
      if (floater) {
        floater.classList.remove("centered-massive-word", "text-fade-visible");
        floater.classList.add("implode-into-core");
        setTimeout(() => {
          floater.remove();
          document.querySelectorAll(".floating-letter").forEach((node) => {
            if (node.textContent?.trim() === "MODE X") {
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

    return () => {
      window.removeEventListener("resize", resize);
      if (animationId) cancelAnimationFrame(animationId);
      if (rocketAnimationId) cancelAnimationFrame(rocketAnimationId);
      if (warpInterval) clearInterval(warpInterval);
      if (resizeObserver) resizeObserver.disconnect();
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
          <p>RELEASING SOON</p>
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