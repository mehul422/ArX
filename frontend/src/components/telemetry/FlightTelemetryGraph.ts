type TelemetryInputs = {
  apogeeFt: number;
  velocityMs: number;
};

type TelemetryMarker = {
  id: string;
  label: string;
  t: number;
  y: number;
  x: number;
  yPx: number;
  detail: string;
};

type GraphConfig = {
  gridLinesX?: number;
  gridLinesY?: number;
  debounceMs?: number;
};

const M_TO_FT = 3.28084;
const G_FT = 32.174;

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

export class FlightTelemetryGraph {
  private container: HTMLElement;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D | null;
  private tooltip: HTMLDivElement;
  private config: GraphConfig;
  private resizeObserver: ResizeObserver | null = null;
  private debounceTimer: number | null = null;
  private inputs: TelemetryInputs = { apogeeFt: 0, velocityMs: 0 };
  private curve: Array<{ t: number; y: number }> = [];
  private markers: TelemetryMarker[] = [];
  private totalTime = 0;
  private yMax = 0;
  private hoverTime: number | null = null;
  private hoverMarkerId: string | null = null;
  private scrubTime: number | null = null;
  private isDragging = false;

  constructor(container: HTMLElement, config: GraphConfig = {}) {
    this.container = container;
    this.config = { gridLinesX: 6, gridLinesY: 4, debounceMs: 140, ...config };
    const existingCanvas = container.querySelector("canvas");
    this.canvas = existingCanvas || document.createElement("canvas");
    if (!existingCanvas) {
      this.canvas.width = 320;
      this.canvas.height = 120;
      container.appendChild(this.canvas);
    }
    this.canvas.classList.add("telemetry-canvas");
    this.ctx = this.canvas.getContext("2d");

    this.tooltip = document.createElement("div");
    this.tooltip.className = "telemetry-tooltip";
    this.tooltip.setAttribute("aria-hidden", "true");
    this.container.appendChild(this.tooltip);

    this.bindEvents();
    this.observeResize();
    this.resize();
    this.render();
  }

  dispose() {
    this.resizeObserver?.disconnect();
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    this.canvas.removeEventListener("pointerup", this.handlePointerUp);
    this.canvas.removeEventListener("pointercancel", this.handlePointerUp);
    if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
    this.tooltip.remove();
  }

  setInputs(apogeeFt: number, velocityMs: number) {
    this.inputs = { apogeeFt, velocityMs };
    if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
    this.debounceTimer = window.setTimeout(() => {
      this.computeCurve();
      this.render();
    }, this.config.debounceMs);
  }

  private bindEvents() {
    this.canvas.addEventListener("pointermove", this.handlePointerMove);
    this.canvas.addEventListener("pointerleave", this.handlePointerLeave);
    this.canvas.addEventListener("pointerdown", this.handlePointerDown);
    this.canvas.addEventListener("pointerup", this.handlePointerUp);
    this.canvas.addEventListener("pointercancel", this.handlePointerUp);
  }

  private observeResize() {
    this.resizeObserver = new ResizeObserver(() => {
      this.resize();
      this.render();
    });
    this.resizeObserver.observe(this.container);
  }

  private resize() {
    const rect = this.container.getBoundingClientRect();
    const nextWidth = Math.max(240, Math.floor(rect.width));
    const nextHeight = Math.max(120, Math.floor(rect.height));
    if (this.canvas.width !== nextWidth) this.canvas.width = nextWidth;
    if (this.canvas.height !== nextHeight) this.canvas.height = nextHeight;
  }

  private computeCurve() {
    const apogeeFt = this.inputs.apogeeFt;
    const velocityMs = this.inputs.velocityMs;
    if (!Number.isFinite(apogeeFt) || !Number.isFinite(velocityMs) || apogeeFt <= 0 || velocityMs <= 0) {
      this.curve = [];
      this.markers = [];
      this.totalTime = 0;
      this.yMax = 0;
      return;
    }
    const v0 = Math.max(velocityMs * M_TO_FT, 1);
    const totalTime = clamp((4 * apogeeFt) / v0, 1.5, 5000);
    const tPeak = totalTime / 2;
    const coef = (4 * apogeeFt) / (totalTime * totalTime);
    this.yMax = Math.max(apogeeFt * 1.05, 1);

    const samples = 140;
    this.curve = Array.from({ length: samples }, (_, i) => {
      const t = (i / (samples - 1)) * totalTime;
      const y = Math.max(0, apogeeFt - coef * Math.pow(t - tPeak, 2));
      return { t, y };
    });
    this.totalTime = totalTime;

    const maxQTime = tPeak * 0.35;
    const chuteAlt = clamp(apogeeFt * 0.18, 600, Math.min(apogeeFt * 0.6, 9000));
    const chuteDelta = Math.sqrt(Math.max(0, (apogeeFt - chuteAlt) * totalTime * totalTime / (4 * apogeeFt)));
    const chuteTime = clamp(tPeak + chuteDelta, tPeak, totalTime);

    const liftOff: TelemetryMarker = {
      id: "liftoff",
      label: "LIFTOFF",
      t: 0,
      y: 0,
      x: 0,
      yPx: 0,
      detail: "Ignition confirmed",
    };
    const maxQ: TelemetryMarker = {
      id: "maxq",
      label: "MAX Q",
      t: maxQTime,
      y: this.altitudeAt(maxQTime),
      x: 0,
      yPx: 0,
      detail: "Max dynamic pressure",
    };
    const apogee: TelemetryMarker = {
      id: "apogee",
      label: "APOGEE",
      t: tPeak,
      y: apogeeFt,
      x: 0,
      yPx: 0,
      detail: "Peak altitude",
    };
    const chute: TelemetryMarker = {
      id: "chute",
      label: "PARA DEPLOY",
      t: chuteTime,
      y: chuteAlt,
      x: 0,
      yPx: 0,
      detail: "Recovery sequence",
    };
    const landing: TelemetryMarker = {
      id: "landing",
      label: "LANDING",
      t: totalTime,
      y: 0,
      x: 0,
      yPx: 0,
      detail: "Touchdown",
    };
    this.markers = [liftOff, maxQ, apogee, chute, landing];
  }

  private altitudeAt(time: number) {
    if (!this.totalTime || !this.inputs.apogeeFt) return 0;
    const tPeak = this.totalTime / 2;
    const coef = (4 * this.inputs.apogeeFt) / (this.totalTime * this.totalTime);
    return Math.max(0, this.inputs.apogeeFt - coef * Math.pow(time - tPeak, 2));
  }

  private plotToCanvas(t: number, y: number) {
    const padX = 16;
    const padY = 12;
    const width = this.canvas.width - padX * 2;
    const height = this.canvas.height - padY * 2;
    const x = padX + (this.totalTime ? (t / this.totalTime) * width : 0);
    const yPx = padY + height - (this.yMax ? (y / this.yMax) * height : 0);
    return { x, yPx };
  }

  private handlePointerMove = (event: PointerEvent) => {
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
      this.hoverTime = null;
      this.hoverMarkerId = null;
      this.hideTooltip();
      this.render();
      return;
    }

    const time = this.timeFromX(x);
    this.hoverTime = time;

    let closest: TelemetryMarker | null = null;
    let closestDist = 60;
    for (const marker of this.markers) {
      const pos = this.plotToCanvas(marker.t, marker.y);
      const dist = Math.hypot(pos.x - x, pos.yPx - y);
      if (dist < closestDist) {
        closest = marker;
        closestDist = dist;
      }
    }

    this.hoverMarkerId = closest?.id || null;
    if (closest) {
      const markerPos = this.plotToCanvas(closest.t, closest.y);
      this.showTooltip(
        `${closest.label} • t=${closest.t.toFixed(1)}s • ${Math.round(closest.y)} ft`,
        markerPos.x,
        markerPos.yPx
      );
    } else {
      this.hideTooltip();
    }
    this.render();
  };

  private handlePointerLeave = () => {
    this.hoverTime = null;
    this.hoverMarkerId = null;
    this.hideTooltip();
    if (!this.isDragging) {
      this.scrubTime = null;
    }
    this.render();
  };

  private handlePointerDown = (event: PointerEvent) => {
    if (!this.totalTime) return;
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    this.isDragging = true;
    this.scrubTime = this.timeFromX(x);
    this.canvas.setPointerCapture(event.pointerId);
    this.render();
  };

  private handlePointerUp = (event: PointerEvent) => {
    if (this.isDragging) {
      this.isDragging = false;
      this.canvas.releasePointerCapture(event.pointerId);
      this.render();
    }
  };

  private timeFromX(x: number) {
    const padX = 16;
    const width = this.canvas.width - padX * 2;
    const ratio = clamp((x - padX) / width, 0, 1);
    return ratio * this.totalTime;
  }

  private showTooltip(text: string, x: number, y: number) {
    this.tooltip.textContent = text;
    this.tooltip.style.opacity = "1";
    this.tooltip.style.transform = `translate(${x + 8}px, ${Math.max(6, y - 24)}px)`;
  }

  private hideTooltip() {
    this.tooltip.style.opacity = "0";
  }

  private renderGrid() {
    if (!this.ctx) return;
    const { gridLinesX = 6, gridLinesY = 4 } = this.config;
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const padX = 16;
    const padY = 12;
    ctx.save();
    ctx.strokeStyle = "rgba(0, 180, 255, 0.12)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= gridLinesX; i += 1) {
      const x = padX + (i / gridLinesX) * (w - padX * 2);
      ctx.beginPath();
      ctx.moveTo(x, padY);
      ctx.lineTo(x, h - padY);
      ctx.stroke();
    }
    for (let i = 0; i <= gridLinesY; i += 1) {
      const y = padY + (i / gridLinesY) * (h - padY * 2);
      ctx.beginPath();
      ctx.moveTo(padX, y);
      ctx.lineTo(w - padX, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  private renderAxes() {
    if (!this.ctx) return;
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const padX = 16;
    const padY = 12;
    ctx.save();
    ctx.strokeStyle = "rgba(0, 255, 196, 0.55)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(padX, padY);
    ctx.lineTo(padX, h - padY);
    ctx.lineTo(w - padX, h - padY);
    ctx.stroke();

    ctx.fillStyle = "rgba(0, 255, 196, 0.65)";
    ctx.font = "10px 'Orbitron', sans-serif";
    ctx.fillText("ALT (FT)", 2, padY - 2);
    ctx.fillText("TIME (S)", w - padX - 46, h - padY + 12);

    if (this.yMax > 0) {
      ctx.fillStyle = "rgba(160, 255, 220, 0.75)";
      ctx.fillText("0", padX - 10, h - padY + 4);
      ctx.fillText(`${Math.round(this.yMax)}`, padX - 10, padY + 8);
      ctx.fillText(`${Math.round(this.yMax * 0.5)}`, padX - 10, (h + padY) / 2);
    }
    if (this.totalTime > 0) {
      ctx.fillStyle = "rgba(160, 255, 220, 0.75)";
      ctx.fillText("0", padX, h - padY + 18);
      ctx.fillText(`${this.totalTime.toFixed(1)}`, w - padX - 18, h - padY + 18);
      ctx.fillText(`${(this.totalTime * 0.5).toFixed(1)}`, w / 2 - 8, h - padY + 18);
    }
    ctx.restore();
  }

  private renderCurve() {
    if (!this.ctx || !this.curve.length) return;
    const ctx = this.ctx;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.strokeStyle = "rgba(0, 255, 196, 0.6)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    this.curve.forEach((point, index) => {
      const pos = this.plotToCanvas(point.t, point.y);
      if (index === 0) ctx.moveTo(pos.x, pos.yPx);
      else ctx.lineTo(pos.x, pos.yPx);
    });
    ctx.stroke();

    const highlightTime = this.isDragging ? this.scrubTime : this.hoverTime;
    if (highlightTime != null) {
      const delta = this.totalTime * 0.08;
      const start = Math.max(0, highlightTime - delta);
      const end = Math.min(this.totalTime, highlightTime + delta);
      ctx.strokeStyle = "rgba(0, 255, 255, 0.95)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      this.curve.forEach((point) => {
        if (point.t < start || point.t > end) return;
        const pos = this.plotToCanvas(point.t, point.y);
        if (point.t === start) ctx.moveTo(pos.x, pos.yPx);
        else ctx.lineTo(pos.x, pos.yPx);
      });
      ctx.stroke();
    }
    ctx.restore();
  }

  private renderMarkers() {
    if (!this.ctx || !this.markers.length) return;
    const ctx = this.ctx;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (const marker of this.markers) {
      const pos = this.plotToCanvas(marker.t, marker.y);
      marker.x = pos.x;
      marker.yPx = pos.yPx;
      const isActive = marker.id === this.hoverMarkerId;
      ctx.fillStyle = isActive ? "rgba(0, 255, 255, 0.95)" : "rgba(0, 255, 170, 0.65)";
      ctx.beginPath();
      ctx.arc(pos.x, pos.yPx, isActive ? 4 : 3, 0, Math.PI * 2);
      ctx.fill();
      if (isActive) {
        const label = marker.label;
        ctx.font = "10px 'Orbitron', sans-serif";
        const textWidth = ctx.measureText(label).width;
        const paddingX = 6;
        const paddingY = 4;
        const boxWidth = textWidth + paddingX * 2;
        const boxHeight = 16;
        const boxX = pos.x + 10;
        const boxY = pos.yPx - boxHeight - 6;
        ctx.globalCompositeOperation = "source-over";
        ctx.fillStyle = "rgba(4, 16, 18, 0.75)";
        ctx.strokeStyle = "rgba(0, 255, 204, 0.5)";
        ctx.lineWidth = 1;
        this.drawRoundedRect(ctx, boxX, boxY, boxWidth, boxHeight, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "rgba(180, 255, 255, 0.95)";
        ctx.fillText(label, boxX + paddingX, boxY + boxHeight - paddingY);
        ctx.globalCompositeOperation = "lighter";
      }
    }
    ctx.restore();
  }

  private renderScrubber() {
    if (!this.ctx || this.scrubTime == null || !this.totalTime) return;
    const ctx = this.ctx;
    const pos = this.plotToCanvas(this.scrubTime, this.altitudeAt(this.scrubTime));
    ctx.save();
    ctx.strokeStyle = "rgba(0, 255, 255, 0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pos.x, 12);
    ctx.lineTo(pos.x, this.canvas.height - 12);
    ctx.stroke();
    ctx.fillStyle = "rgba(0, 255, 255, 0.85)";
    ctx.beginPath();
    ctx.arc(pos.x, pos.yPx, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  private renderEmptyState() {
    if (!this.ctx) return;
    this.renderGrid();
    this.renderAxes();
  }

  render() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.curve.length) {
      this.renderEmptyState();
      return;
    }
    this.renderGrid();
    this.renderAxes();
    this.renderCurve();
    this.renderMarkers();
    this.renderScrubber();
  }

  private drawRoundedRect(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
  ) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.arcTo(x + width, y, x + width, y + r, r);
    ctx.lineTo(x + width, y + height - r);
    ctx.arcTo(x + width, y + height, x + width - r, y + height, r);
    ctx.lineTo(x + r, y + height);
    ctx.arcTo(x, y + height, x, y + height - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
  }
}
