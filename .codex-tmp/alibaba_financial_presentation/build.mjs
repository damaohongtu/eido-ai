import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
import { buildSlide01 } from "./codex-grid-compose/slide-01.mjs";
import { buildSlide19 } from "./codex-grid-compose/slide-19.mjs";
import { buildSlide20 } from "./codex-grid-compose/slide-20.mjs";
import { buildSlide21 } from "./codex-grid-compose/slide-21.mjs";
import { buildSlide22 } from "./codex-grid-compose/slide-22.mjs";
import { buildSlide26 } from "./codex-grid-compose/slide-26.mjs";

const OUT_DIR = "/Users/mao/workspace/eido-ai/outputs/alibaba_financial_presentation_20260730";
const PPTX_PATH = path.join(OUT_DIR, "Alibaba_FY2026_Financial_Review.pptx");
const PREVIEW_DIR = "/Users/mao/workspace/eido-ai/.codex-tmp/alibaba_financial_presentation/previews";
const FONT = "PingFang SC";
const C = {
  ink: "#000000",
  white: "#FFFFFF",
  panel: "#F2F2F2",
  rule: "#B8BCC4",
  grid: "#EDEDED",
  accent: "#6DCBF4",
  accentStrong: "#3D8DFF",
  accentPale: "#D0EDFA",
  muted: "#70757D",
};

const URLS = {
  fy26: "https://data.alibabagroup.com/ecms-files/1532295521/5b1cb883-8d00-4237-a148-6631cc12a5d2/Alibaba%20Group%20Announces%20March%20Quarter%202026%20and%20Fiscal%20Year%202026%20Results.pdf",
  fy24: "https://data.alibabagroup.com/ecms-files/1532295521/afdeaf9e-5dd7-4a18-8ff0-968a6807f09d/Alibaba%20Group%20Announces%20March%20Quarter%202024%20and%20Fiscal%20Year%202024%20Results.pdf",
  fy23: "https://data.alibabagroup.com/ecms-files/1532295521/e6f712b2-580c-4adf-ae1b-77c15c1ac262/Alibaba%20Group%20Announces%20March%20Quarter%20and%20Full%20Fiscal%20Year%202023%20Results.pdf",
  fy22: "https://data.alibabagroup.com/ecms-files/1532295521/34596e84-ff0c-4522-bbc8-82a8c49c0bba.pdf",
  reports: "https://www.alibabagroup.com/en-US/ir-financial-reports-financial-results",
};

function tx(run, fontSize, options = {}) {
  return {
    runs: [{
      run,
      textStyle: {
        fontSize,
        typeface: FONT,
        color: options.color ?? C.ink,
        bold: options.bold ?? false,
      },
    }],
    ...(options.spaceAfter ? { spaceAfter: options.spaceAfter } : {}),
    ...(options.spaceBefore ? { spaceBefore: options.spaceBefore } : {}),
    paragraphStyle: { lineSpacingPercent: options.lineSpacingPercent ?? 100000 },
  };
}

function addNotes(slide, presenterText, sources) {
  const sourceLines = sources.map((url) => `- ${url} (accessed 2026-07-30)`).join("\n");
  slide.speakerNotes.textFrame.setText(
    `${presenterText}\n\n[Sources]\n${sourceLines}\n[/Sources]`,
  );
  slide.speakerNotes.setVisible(true);
}

function replaceChart(slide, type, config) {
  for (const chart of [...slide.charts.items]) {
    slide.charts.deleteById(chart.id);
  }
  return slide.charts.add(type, config);
}

function commonChartArea() {
  return {
    chartFill: C.white,
    chartLine: { style: "solid", width: 0, fill: C.white },
    plotAreaFill: { type: "none" },
    plotAreaLine: { style: "solid", width: 0, fill: C.white },
  };
}

function axisText(size = 12) {
  return { typeface: FONT, fontSize: size, fill: C.ink };
}

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });

  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  const slide1 = buildSlide01(presentation, {
    title: tx("ALIBABA GROUP · INVESTOR VIEW", "24px", { bold: true, spaceBefore: 1000 }),
    title2: tx("阿里巴巴集团\nFY2026 财务回顾", "80px", { bold: true, lineSpacingPercent: 90000 }),
    title3: tx("增长延续，投资重置利润与现金流｜截至 2026 年 3 月", "32px"),
  });
  addNotes(slide1, "开场：本报告聚焦增长质量、盈利重置和现金流修复，而不是短期股价判断。", [URLS.reports, URLS.fy26]);

  const slide2 = buildSlide19(presentation, {
    title: tx("FY2026 是战略投入年：收入增长，利润与现金流承压", "38.67px", { bold: true }),
    body1: {
      topic: tx("核心判断", "21.33px", { bold: true, spaceAfter: 600 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx(
        "集团规模继续扩张，但即时零售、AI、云基础设施和用户体验投入显著压低当期盈利。下一阶段的关键不只是增长，而是增长能否重新转化为自由现金流。",
        "21.33px",
        { lineSpacingPercent: 114000 },
      ),
    },
    stat1: tx("+3%", "32px", { bold: true }),
    stat2: tx("−56%", "32px", { bold: true }),
    stat3: tx("−RMB46.6bn", "32px", { bold: true }),
    body2: tx("收入同比\nRMB 1,023.7bn", "21.33px"),
    body3: tx("经调整 EBITA\n同比下降", "21.33px"),
    body4: tx("自由现金流\n由正转负", "21.33px"),
    footer1: tx("02", "13.33px"),
  });
  addNotes(slide2, "强调三件事：收入韧性、利润投入强度、自由现金流转负。", [URLS.fy26]);

  const slide3 = buildSlide21(presentation, {
    title: tx("五年看规模稳步扩大，但盈利弹性明显减弱", "38.67px", { bold: true }),
    body1: tx("指数化后，FY2026 收入较 FY2022 高约 20%；经调整 EBITA 则跌至 FY2022 的约 59%。", "21.33px", { lineSpacingPercent: 114000 }),
    stat1: tx("120", "32px", { bold: true }),
    stat2: tx("59", "32px", { bold: true }),
    body2: tx("收入指数\nFY22 = 100", "18.67px"),
    body3: tx("经调整 EBITA\nFY22 = 100", "18.67px"),
    footer1: tx("03", "13.33px"),
  });
  replaceChart(slide3, "line", {
    position: { left: 40.51, top: 131.73, width: 581.02, height: 527.51 },
    categories: ["FY22", "FY23", "FY24", "FY25", "FY26"],
    series: [
      { name: "收入指数", values: [100.0, 101.8, 110.3, 116.8, 120.0], line: { style: "solid", width: 4, fill: C.accentStrong }, marker: { symbol: "circle", size: 7 } },
      { name: "经调整 EBITA 指数", values: [100.0, 113.4, 126.6, 132.7, 58.6], line: { style: "solid", width: 4, fill: C.accent }, marker: { symbol: "circle", size: 7 } },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: axisText(12) },
    lineOptions: { grouping: "standard", smooth: false },
    xAxis: { visible: true, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(12) },
    yAxis: { visible: true, min: 40, max: 140, majorUnit: 20, numberFormatCode: "0", majorGridlines: { style: "solid", width: 1, fill: C.grid }, line: { style: "solid", width: 0, fill: C.white }, textStyle: axisText(12) },
    dataLabels: { showValue: false },
    ...commonChartArea(),
  });
  addNotes(slide3, "图表以 FY2022=100 进行指数化，便于比较收入与经调整 EBITA 的趋势，而不是绝对规模。", [URLS.fy22, URLS.fy23, URLS.fy24, URLS.fy26]);

  const slide4 = buildSlide22(presentation, {
    title: tx("利润重置集中发生在 FY2026", "38.67px", { bold: true }),
    body1: {
      titleHere: tx("投入压低短期利润", "24px", { bold: true, spaceAfter: 800 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("经营利润和经调整 EBITA 降幅最深；净利润韧性相对更好，但仍同比下降 19%。", "21.33px", { lineSpacingPercent: 114000 }),
    },
    stat1: tx("−64%", "32px", { bold: true }),
    stat2: tx("−56%", "32px", { bold: true }),
    body2: tx("经营利润\n同比", "18.67px"),
    body3: tx("经调整 EBITA\n同比", "18.67px"),
    footer1: tx("04", "13.33px"),
  });
  replaceChart(slide4, "bar", {
    position: { left: 66.61, top: 138.84, width: 528.06, height: 502.32 },
    categories: ["经营利润", "经调整 EBITA", "净利润"],
    series: [
      { name: "FY2025", values: [140.9, 173.1, 126.0], fill: C.accentPale, valuesFormatCode: "0.0" },
      { name: "FY2026", values: [50.2, 76.4, 102.1], fill: C.accentStrong, valuesFormatCode: "0.0" },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: axisText(12) },
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 65 },
    xAxis: { visible: true, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    yAxis: { visible: true, min: 0, max: 200, majorUnit: 50, numberFormatCode: "0", majorGridlines: { style: "solid", width: 1, fill: C.grid }, line: { style: "solid", width: 0, fill: C.white }, textStyle: axisText(11) },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { ...axisText(11), bold: true } },
    ...commonChartArea(),
  });
  addNotes(slide4, "管理层将利润下降归因于即时零售、用户体验、AI 和云基础设施等投入。图中单位为人民币十亿元。", [URLS.fy26]);

  const slide5 = buildSlide20(presentation, {
    title: tx("现金流压力比收入放缓更值得关注", "38.67px", { bold: true }),
    body1: {
      titleGoesHere: tx("经营现金流 −53%", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("FY2026 降至 RMB76.2bn。", "18.67px"),
    },
    body2: {
      titleGoesHere: tx("自由现金流转负", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("由 +73.9bn 降至 −46.6bn。", "18.67px"),
    },
    body3: {
      titleGoesHere: tx("流动性仍充足", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("现金及流动投资 RMB520.8bn。", "18.67px"),
    },
    footer1: tx("05", "13.33px"),
  });
  replaceChart(slide5, "bar", {
    position: { left: 42.91, top: 110.67, width: 537.97, height: 572.39 },
    categories: ["现金及流动投资", "自由现金流", "经营现金流"],
    series: [
      { name: "FY2025", values: [597.1, 73.9, 163.5], fill: C.accentPale, valuesFormatCode: "0.0" },
      { name: "FY2026", values: [520.8, -46.6, 76.2], fill: C.accentStrong, valuesFormatCode: "0.0" },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: axisText(12) },
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 45 },
    xAxis: { visible: true, min: -100, max: 650, majorUnit: 150, numberFormatCode: "0", majorGridlines: { style: "solid", width: 1, fill: C.grid }, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    yAxis: { visible: true, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { ...axisText(10), bold: true } },
    ...commonChartArea(),
  });
  addNotes(slide5, "自由现金流下降主要反映即时零售投入和云基础设施资本开支。图中单位为人民币十亿元。", [URLS.fy26]);

  const slide6 = buildSlide22(presentation, {
    title: tx("FY2026 盈利漏斗显示：规模大，利润转化变薄", "38.67px", { bold: true }),
    body1: {
      titleHere: tx("从收入到经营利润", "24px", { bold: true, spaceAfter: 800 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("毛利仍提供缓冲，但从经调整 EBITDA 到经营利润的落差反映投资和费用压力。", "21.33px", { lineSpacingPercent: 114000 }),
    },
    stat1: tx("39.8%", "32px", { bold: true }),
    stat2: tx("4.9%", "32px", { bold: true }),
    body2: tx("毛利率", "18.67px"),
    body3: tx("经营利润率", "18.67px"),
    footer1: tx("06", "13.33px"),
  });
  replaceChart(slide6, "bar", {
    position: { left: 66.61, top: 138.84, width: 528.06, height: 502.32 },
    categories: ["经营利润", "经调整 EBITA", "经调整 EBITDA", "毛利", "收入"],
    series: [
      { name: "FY2026", values: [50.2, 76.4, 113.5, 407.5, 1023.7], fill: C.accentStrong, valuesFormatCode: "0.0" },
    ],
    hasLegend: false,
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 38 },
    xAxis: { visible: true, min: 0, max: 1150, majorUnit: 250, numberFormatCode: "0", majorGridlines: { style: "solid", width: 1, fill: C.grid }, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    yAxis: { visible: true, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { ...axisText(10), bold: true } },
    ...commonChartArea(),
  });
  addNotes(slide6, "口径依次为收入、毛利、经调整 EBITDA、经调整 EBITA 和经营利润。图中单位为人民币十亿元。", [URLS.fy26]);

  const slide7 = buildSlide20(presentation, {
    title: tx("云智能成为最清晰的增长引擎", "38.67px", { bold: true }),
    body1: {
      titleGoesHere: tx("Cloud +34%", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("FY2026 收入 RMB158.1bn。", "18.67px"),
    },
    body2: {
      titleGoesHere: tx("核心电商 +9%", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("中国电商与国际业务均增长 9%。", "18.67px"),
    },
    body3: {
      titleGoesHere: tx("其他业务 −25%", "26.67px", { bold: true, spaceAfter: 500 }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: tx("组合结构收缩，增长更集中。", "18.67px"),
    },
    footer1: tx("07", "13.33px"),
  });
  replaceChart(slide7, "bar", {
    position: { left: 42.91, top: 110.67, width: 537.97, height: 572.39 },
    categories: ["其他业务", "国际数字商业", "中国电商", "云智能"],
    series: [
      { name: "FY2025", values: [338.3, 132.3, 508.4, 118.0], fill: C.accentPale, valuesFormatCode: "0.0" },
      { name: "FY2026", values: [254.4, 144.2, 554.2, 158.1], fill: C.accentStrong, valuesFormatCode: "0.0" },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: axisText(12) },
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 40 },
    xAxis: { visible: true, min: 0, max: 620, majorUnit: 150, numberFormatCode: "0", majorGridlines: { style: "solid", width: 1, fill: C.grid }, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    yAxis: { visible: true, line: { style: "solid", width: 1, fill: C.rule }, textStyle: axisText(11) },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { ...axisText(10), bold: true } },
    ...commonChartArea(),
  });
  addNotes(slide7, "分部收入为披露口径，未扣除未分配项目和分部间抵销。图中单位为人民币十亿元。", [URLS.fy26]);

  const slide8 = buildSlide26(presentation, {
    title: tx("NEXT", "24px", { bold: true, spaceBefore: 1000 }),
    title2: tx("增长仍在。\n现金回归是下一关。", "80px", { bold: true, lineSpacingPercent: 90000 }),
    title3: {
      loremIpsumDetails: tx("01  云商业化", "22px"),
      loremIpsumDetails2: tx("02  投入效率", "22px"),
      loremIpsumDetails3: tx("03  现金流修复", "22px"),
    },
  });
  addNotes(slide8, "收束：增长故事的验证点已经从收入本身转向云商业化、投入效率和自由现金流修复。", [URLS.fy26]);

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(PREVIEW_DIR, `${stem}.png`), await presentation.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(PREVIEW_DIR, `${stem}.layout.json`), await layout.text());
  }

  await writeBlob(path.join(PREVIEW_DIR, "deck-montage.webp"), await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(PPTX_PATH);
  console.log(PPTX_PATH);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
