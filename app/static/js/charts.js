// Small local renderer: data remains separate from SVG and accessible tables.
const NS = "http://www.w3.org/2000/svg";
function svgElement(tag, attributes = {}, text) {
  const item = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, value);
  if (text != null) item.textContent = text;
  return item;
}
function html(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
const shortDate = (date) => date.slice(5).replace("-", "/");

/** Points are equally spaced, so callers supply every day/week, including nulls. */
export function renderChart(container, {title, points, kind = "line", unit, format, zeroBaseline = true, integer = false, connectGaps = false}) {
  container.replaceChildren();
  const available = points.filter((point) => point.value != null);
  if (!available.length) {
    container.append(html("p", "선택한 기간에 표시할 기록이 없습니다.", "empty-state"));
    return () => {};
  }
  const interactive = html("div", null, "chart-interactive");
  interactive.tabIndex = 0;
  interactive.setAttribute("role", "group");
  interactive.setAttribute("aria-label", title + ". 좌우 방향키로 날짜별 값을 확인하세요.");
  const readout = html("p", "", "chart-readout");
  readout.setAttribute("aria-live", "polite");
  const instructions = html("p", "차트를 누르거나 좌우 방향키로 값을 확인하세요.", "chart-instructions");
  const details = html("details", null, "data-details");
  details.append(html("summary", "숫자로 보기 · " + points.length + "개 구간"));
  const scroll = html("div", null, "table-scroll");
  const table = html("table");
  table.append(html("caption", title + " · " + unit));
  const head = html("thead"), header = html("tr");
  for (const label of ["날짜 / 기간", unit]) { const th = html("th", label); th.scope = "col"; header.append(th); }
  head.append(header); table.append(head);
  const body = html("tbody");
  for (const point of points) {
    const row = html("tr");
    row.append(html("td", point.label || point.date), html("td", point.value == null ? (point.missingLabel || "미기록") : format(point.value), "number"));
    body.append(row);
  }
  table.append(body); scroll.append(table); details.append(scroll);
  container.append(interactive, readout, instructions, details);
  let selected = points.findLastIndex((point) => point.value != null);
  const select = (index) => {
    selected = Math.max(0, Math.min(points.length - 1, index));
    const point = points[selected];
    readout.textContent = (point.label || point.date) + " · " + (point.value == null ? (point.missingLabel || "미기록") : format(point.value) + " " + unit);
    draw();
  };
  function draw() {
    const width = Math.max(220, interactive.clientWidth), height = 240;
    const left = 54, right = 18, top = 18, bottom = 36;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    const values = available.map((point) => point.value);
    let low = zeroBaseline ? 0 : Math.min(...values), high = Math.max(...values);
    if (!zeroBaseline) {
      const pad = Math.max((high - low) * .15, .5);
      low = Math.max(0, low - pad); high += pad;
    } else high = Math.max(high * 1.12, integer ? 2 : 1);
    if (integer) high = Math.max(2, Math.ceil(high / 2) * 2);
    if (high <= low) high = low + 1;
    const x = (index) => left + (kind === "bar" ? (index + .5) / points.length : points.length === 1 ? .5 : index / (points.length - 1)) * plotWidth;
    const y = (value) => top + (1 - (value - low) / (high - low)) * plotHeight;
    const svg = svgElement("svg", {viewBox: "0 0 " + width + " " + height, class: "chart-svg", role: "img", "aria-label": title});
    svg.append(svgElement("title", {}, title + " (" + unit + "). 아래 표에서 정확한 값을 확인할 수 있습니다."));
    for (const value of [low, (low + high) / 2, high]) {
      svg.append(svgElement("line", {x1:left,y1:y(value),x2:width-right,y2:y(value),class:"chart-gridline"}));
      const label = new Intl.NumberFormat("ko-KR", {maximumFractionDigits:integer ? 0 : 1, notation:Math.abs(value) >= 100000 ? "compact" : "standard"}).format(value);
      svg.append(svgElement("text", {x:left-8,y:y(value)+4,"text-anchor":"end",class:"chart-axis"}, label));
    }
    const ticks = Math.min(width < 450 ? 3 : 5, points.length);
    const tickIndices = new Set(Array.from({length:ticks}, (_, index) => ticks === 1 ? 0 : Math.round(index * (points.length-1)/(ticks-1))));
    for (const index of tickIndices) svg.append(svgElement("text", {x:x(index),y:height-10,"text-anchor":"middle",class:"chart-axis"}, shortDate(points[index].date)));
    if (kind === "bar") {
      const barWidth = Math.min(42, plotWidth / points.length * .65);
      points.forEach((point, index) => {
        if (point.value == null) return;
        svg.append(svgElement("rect", {x:x(index)-barWidth/2,y:y(point.value),width:barWidth,height:Math.max(0, y(0)-y(point.value)),rx:2,class:index === selected ? "chart-bar chart-bar-selected" : "chart-bar"}));
      });
    } else {
      let path = "", connected = false;
      points.forEach((point, index) => {
        if (point.value == null) { if (!connectGaps) connected = false; return; }
        path += (connected ? "L" : "M") + x(index) + "," + y(point.value) + " ";
        connected = true;
      });
      svg.append(svgElement("path", {d:path,class:"chart-line"}));
      points.forEach((point,index) => {
        if (point.value != null) svg.append(svgElement("circle", {cx:x(index),cy:y(point.value),r:points.length > 90 ? 2 : 3.5,class:"chart-dot"}));
      });
    }
    if (kind !== "bar" && points[selected]?.value != null) svg.append(svgElement("circle", {cx:x(selected),cy:y(points[selected].value),r:5,class:"chart-selected"}));
    svg.addEventListener("click", (event) => {
      const ratio = Math.max(0, Math.min(1, (event.clientX-svg.getBoundingClientRect().left-left)/plotWidth));
      select(kind === "bar" ? Math.min(points.length-1,Math.floor(ratio*points.length)) : Math.round(ratio*(points.length-1)));
    });
    interactive.replaceChildren(svg);
  }
  interactive.addEventListener("keydown", (event) => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault();
    select(event.key === "Home" ? 0 : event.key === "End" ? points.length-1 : selected + (event.key === "ArrowRight" ? 1 : -1));
  });
  const observer = new ResizeObserver(draw);
  observer.observe(interactive);
  select(selected);
  return () => observer.disconnect();
}
