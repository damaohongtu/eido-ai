import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const templatePath = "/Users/mao/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.0/skills/artifact-template-analytics-dashboard/assets/reference.xlsx";
const workDir = "/Users/mao/workspace/eido-ai/.codex-tmp/alibaba_financial_dashboard";
const outputDir = "/Users/mao/workspace/eido-ai/outputs/alibaba_financial_dashboard_20260730";
const outputPath = `${outputDir}/Alibaba_Financial_Dashboard_FY2026.xlsx`;

const sources = {
  fy2026: "https://data.alibabagroup.com/ecms-files/1532295521/5b1cb883-8d00-4237-a148-6631cc12a5d2/Alibaba%20Group%20Announces%20March%20Quarter%202026%20and%20Fiscal%20Year%202026%20Results.pdf",
  fy2024: "https://data.alibabagroup.com/ecms-files/1532295521/afdeaf9e-5dd7-4a18-8ff0-968a6807f09d/Alibaba%20Group%20Announces%20March%20Quarter%202024%20and%20Fiscal%20Year%202024%20Results.pdf",
  fy2023: "https://data.alibabagroup.com/ecms-files/1532295521/e6f712b2-580c-4adf-ae1b-77c15c1ac262/Alibaba%20Group%20Announces%20March%20Quarter%20and%20Full%20Fiscal%20Year%202023%20Results.pdf",
  fy2022: "https://data.alibabagroup.com/ecms-files/1532295521/34596e84-ff0c-4522-bbc8-82a8c49c0bba.pdf",
  reports: "https://www.alibabagroup.com/en-US/ir-financial-reports-financial-results",
};

const input = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const dashboard = workbook.worksheets.getItem("Dashboard");
const data = workbook.worksheets.getItem("Data & Targets");
const helpers = workbook.worksheets.getItem("_Chart Helpers");

workbook.comments.setSelf({ displayName: "User" });

// Official annual results, RMB billions. Fiscal year ends March 31.
const annuals = [
  [new Date(Date.UTC(2022, 2, 31)), 853.062, 69.638, 130.397, 47.079, 142.759, 98.874, 446.412],
  [new Date(Date.UTC(2023, 2, 31)), 868.687, 100.351, 147.911, 65.573, 199.752, 171.663, 560.314],
  [new Date(Date.UTC(2024, 2, 31)), 941.168, 113.350, 165.028, 71.332, 182.593, 156.210, 617.230],
  [new Date(Date.UTC(2025, 2, 31)), 996.347, 140.905, 173.065, 125.976, 163.509, 73.870, 597.132],
  [new Date(Date.UTC(2026, 2, 31)), 1023.670, 50.150, 76.416, 102.127, 76.213, -46.609, 520.824],
];

// Data sheet: retain the template's structure and input styling, replace synthetic content only.
data.getRange("B2").values = [["Alibaba Group Financial Dashboard"]];
data.getRange("B3").values = [["Financial Data & Comparatives"]];
data.getRange("B6").values = [["Official fiscal-year data are shown in RMB billions. Green values are sourced historical inputs; black cells are formulas."]];
data.getRange("B7").values = [["Choose a fiscal year in C9. The dashboard updates headline metrics, prior-year comparisons, FY2022 baselines, charts, and status checks."]];
data.getRange("B9").values = [["Selected Fiscal Year"]];
data.getRange("C9").values = [[new Date(Date.UTC(2026, 2, 31))]];
data.getRange("B10").values = [["Data Current Through"]];
data.getRange("C10").formulas = [["=MAX($B$16:$B$20)"]];
data.getRange("B11").values = [["Source Note"]];
data.getRange("C11").values = [[`Official Alibaba Group financial results and annual reports. Latest results: ${sources.fy2026} | Archive: ${sources.reports}`]];
data.getRange("B13").values = [["ANNUAL FINANCIALS & PRIOR-YEAR COMPARATIVES — RMB BILLIONS"]];

data.getRange("B15:P15").values = [[
  "Fiscal Year",
  "Revenue",
  "Operating Income",
  "Adjusted EBITA",
  "Net Income",
  "Operating Cash Flow",
  "Free Cash Flow",
  "Cash & Liquid Investments",
  "Prior Revenue",
  "Prior Operating Income",
  "Prior Adjusted EBITA",
  "Prior Net Income",
  "Prior Operating Cash Flow",
  "Prior Free Cash Flow",
  "Prior Cash & Liquid Investments",
]];
data.getRange("B16:P27").clear({ applyTo: "contents" });
data.getRange("B16:I20").values = annuals;
data.getRange("J17:P20").formulas = [
  ["=C16", "=D16", "=E16", "=F16", "=G16", "=H16", "=I16"],
  ["=C17", "=D17", "=E17", "=F17", "=G17", "=H17", "=I17"],
  ["=C18", "=D18", "=E18", "=F18", "=G18", "=H18", "=I18"],
  ["=C19", "=D19", "=E19", "=F19", "=G19", "=H19", "=I19"],
];
data.getRange("B16:B20").format.numberFormat = '"FY"yyyy';
data.getRange("C9:C10").format.numberFormat = '"FY"yyyy';
data.getRange("C16:P27").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
data.getRange("B16:I20").format.font = { color: "#008000" };
data.getRange("J17:P20").format.font = { color: "#000000" };
data.getRange("C11:P11").format.wrapText = true;
data.getRange("C11:P11").format.rowHeight = 42;
data.getRange("C9").dataValidation = { rule: { type: "list", formula1: "='Data & Targets'!$B$16:$B$20" } };

// P&L scale, checks, and current segment data retain the lower template blocks.
data.getRange("B29:E29").clear({ applyTo: "contents" });
data.getRange("B29").values = [["FY2026 EARNINGS SCALE & MODEL CHECKS"]];
data.getRange("B30:C30").values = [["Earnings Scale", "RMB bn"]];
data.getRange("B31:C35").values = [
  ["Revenue", 1023.670],
  ["Gross Profit", 407.534],
  ["Adjusted EBITDA", 113.483],
  ["Adjusted EBITA", 76.416],
  ["Operating Income", 50.150],
];
data.getRange("C31:C35").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
data.getRange("C31:C35").format.font = { color: "#008000" };

data.getRange("G29:J29").clear({ applyTo: "contents" });
data.getRange("G29").values = [["FY2026 SEGMENT REVENUE — PRE-ELIMINATION"]];
data.getRange("G30:H30").values = [["Segment", "RMB bn"]];
data.getRange("G31:H35").clear({ applyTo: "contents" });
data.getRange("G31:H34").values = [
  ["Alibaba China E-commerce", 554.217],
  ["International Digital Commerce", 144.170],
  ["Cloud Intelligence", 158.132],
  ["All Others", 254.367],
];
data.getRange("G35").values = [["Total Pre-Elimination"]];
data.getRange("H35").formulas = [["=SUM($H$31:$H$34)"]];
data.getRange("H31:H35").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
data.getRange("H31:H34").format.font = { color: "#008000" };

data.getRange("G30:H35").copyTo(data.getRange("D30:E35"), "formats");
data.getRange("D30:E30").values = [["Check", "Status"]];
data.getRange("D31:D35").values = [["Latest FY selected"], ["Prior-year data present"], ["Operating margin ties"], ["Segment data present"], ["MODEL STATUS"]];
data.getRange("E31:E35").formulas = [
  ["=IF($C$9=$C$10,\"PASS\",\"CHECK\")"],
  ["=IF(COUNTA($J$20:$P$20)=7,\"PASS\",\"CHECK\")"],
  ["=IF(ABS(INDEX($D$16:$D$20,MATCH($C$9,$B$16:$B$20,0))/INDEX($C$16:$C$20,MATCH($C$9,$B$16:$B$20,0))-'_Chart Helpers'!$B$4)<0.0001,\"PASS\",\"CHECK\")"],
  ["=IF(COUNT($H$31:$H$34)=4,\"PASS\",\"CHECK\")"],
  ["=IF(COUNTIF($E$31:$E$34,\"CHECK\")=0,\"PASS\",\"CHECK\")"],
];
data.getRange("E31:E35").conditionalFormats.deleteAll();
data.getRange("E31:E35").conditionalFormats.add("containsText", { text: "PASS", format: { fill: "#DDEED8", font: { color: "#226622", bold: true } } });
data.getRange("E31:E35").conditionalFormats.add("containsText", { text: "CHECK", format: { fill: "#F6D6D6", font: { color: "#9C1C1C", bold: true } } });
data.getRange("D31:D35").format.wrapText = true;
data.getRange("G31:G35").format.wrapText = true;
data.getRange("D31:D35").format.columnWidth = 22;
data.getRange("G31:G35").format.columnWidth = 28;
data.getRange("D31:H35").format.rowHeight = 28;

// Source comments on the historical rows and latest-period analytical blocks.
const rowSources = [sources.fy2022, sources.fy2023, sources.fy2024, sources.fy2026, sources.fy2026];
for (let i = 0; i < rowSources.length; i += 1) {
  workbook.comments.addThread({ cell: data.getRange(`B${16 + i}`) }, `Source: ${rowSources[i]} | Units converted from RMB millions to RMB billions.`);
}
workbook.comments.addThread({ cell: data.getRange("B31") }, `Source: ${sources.fy2026} | Gross profit is revenue less cost of revenue; adjusted EBITDA/EBITA are Alibaba non-GAAP measures.`);
workbook.comments.addThread({ cell: data.getRange("G31") }, `Source: ${sources.fy2026} | Segment figures are reported before unallocated items and inter-segment eliminations.`);

// Formula-backed helper blocks drive every card and chart.
helpers.getRange("A1:T13").clear({ applyTo: "contents" });
helpers.getRange("A1:F1").values = [["Metric", "Actual", "Prior Year", "FY2022", "Direction", "Status"]];
helpers.getRange("A2:A9").values = [
  ["Revenue"],
  ["Operating Income"],
  ["Operating Margin"],
  ["Adjusted EBITA"],
  ["Net Income"],
  ["Operating Cash Flow"],
  ["Free Cash Flow"],
  ["Cash & Liquid Investments"],
];
helpers.getRange("B2:B9").formulas = [
  ["=INDEX('Data & Targets'!$C$16:$C$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$D$16:$D$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=B3/B2"],
  ["=INDEX('Data & Targets'!$E$16:$E$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$F$16:$F$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$G$16:$G$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$H$16:$H$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$I$16:$I$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
];
helpers.getRange("C2:C9").formulas = [
  ["=INDEX('Data & Targets'!$J$16:$J$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$K$16:$K$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=C3/C2"],
  ["=INDEX('Data & Targets'!$L$16:$L$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$M$16:$M$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$N$16:$N$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$O$16:$O$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
  ["=INDEX('Data & Targets'!$P$16:$P$20,MATCH('Data & Targets'!$C$9,'Data & Targets'!$B$16:$B$20,0))"],
];
helpers.getRange("D2:D9").formulas = [["='Data & Targets'!C16"], ["='Data & Targets'!D16"], ["=D3/D2"], ["='Data & Targets'!E16"], ["='Data & Targets'!F16"], ["='Data & Targets'!G16"], ["='Data & Targets'!H16"], ["='Data & Targets'!I16"]];
helpers.getRange("E2:E9").values = [["Higher"], ["Higher"], ["Higher"], ["Higher"], ["Higher"], ["Higher"], ["Higher"], ["Higher"]];
helpers.getRange("F2").formulas = [["=IF(OR(B2=\"\",C2=\"\"),\"N/A\",IF(B2>=C2,\"Favorable\",IF(B2>=C2*0.95,\"Watch\",\"Unfavorable\")))"]];
helpers.getRange("F2:F9").fillDown();

helpers.getRange("H1:J1").values = [["Fiscal Year", "Revenue", "Net Income"]];
helpers.getRange("L1:N1").values = [["Fiscal Year", "Adjusted EBITA", "Free Cash Flow"]];
for (let i = 0; i < 5; i += 1) {
  const sourceRow = 16 + i;
  const helperRow = 2 + i;
  helpers.getRange(`H${helperRow}`).formulas = [[`=\"FY\"&YEAR('Data & Targets'!B${sourceRow})`]];
  helpers.getRange(`I${helperRow}`).formulas = [[`='Data & Targets'!C${sourceRow}`]];
  helpers.getRange(`J${helperRow}`).formulas = [[`='Data & Targets'!F${sourceRow}`]];
  helpers.getRange(`L${helperRow}`).formulas = [[`=\"FY\"&YEAR('Data & Targets'!B${sourceRow})`]];
  helpers.getRange(`M${helperRow}`).formulas = [[`='Data & Targets'!E${sourceRow}`]];
  helpers.getRange(`N${helperRow}`).formulas = [[`='Data & Targets'!H${sourceRow}`]];
}

helpers.getRange("P1:Q1").values = [["Earnings Scale", "RMB bn"]];
helpers.getRange("P2:P6").formulas = [["='Data & Targets'!B31"], ["='Data & Targets'!B32"], ["='Data & Targets'!B33"], ["='Data & Targets'!B34"], ["='Data & Targets'!B35"]];
helpers.getRange("Q2:Q6").formulas = [["='Data & Targets'!C31"], ["='Data & Targets'!C32"], ["='Data & Targets'!C33"], ["='Data & Targets'!C34"], ["='Data & Targets'!C35"]];
helpers.getRange("S1:T1").values = [["Segment", "Revenue (RMB bn)"]];
helpers.getRange("S2:S5").formulas = [["='Data & Targets'!G31"], ["='Data & Targets'!G32"], ["='Data & Targets'!G33"], ["='Data & Targets'!G34"]];
helpers.getRange("T2:T5").formulas = [["='Data & Targets'!H31"], ["='Data & Targets'!H32"], ["='Data & Targets'!H33"], ["='Data & Targets'!H34"]];
helpers.getRange("B2:D9").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
helpers.getRange("B4:D4").format.numberFormat = '0.0%;[Red](0.0%);-';
helpers.getRange("I2:J6").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
helpers.getRange("M2:N6").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
helpers.getRange("Q2:Q6").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
helpers.getRange("T2:T5").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
helpers.getRange("A1:A9").format.columnWidth = 24;
helpers.getRange("B1:F9").format.columnWidth = 14;
helpers.getRange("H1:H6").format.columnWidth = 12;
helpers.getRange("I1:J6").format.columnWidth = 15;
helpers.getRange("L1:L6").format.columnWidth = 12;
helpers.getRange("M1:N6").format.columnWidth = 16;
helpers.getRange("P1:P6").format.columnWidth = 22;
helpers.getRange("Q1:Q6").format.columnWidth = 14;
helpers.getRange("S1:S5").format.columnWidth = 28;
helpers.getRange("T1:T5").format.columnWidth = 16;

// Dashboard cards and labels.
dashboard.getRange("B2").values = [["Alibaba Group Financial Dashboard"]];
dashboard.getRange("B3").values = [["FY2022–FY2026 | RMB billions unless noted"]];
dashboard.getRange("J2:M2").clear({ applyTo: "contents" });
dashboard.getRange("J2").values = [["SELECTED FISCAL YEAR"]];
dashboard.getRange("J3").formulas = [["='Data & Targets'!$C$9"]];
dashboard.getRange("N2:Q2").clear({ applyTo: "contents" });
dashboard.getRange("N2").values = [["DATA CURRENT THROUGH"]];
dashboard.getRange("N3").formulas = [["='Data & Targets'!$C$10"]];
dashboard.getRange("J3:N3").format.numberFormat = '"FY"yyyy';
dashboard.getRange("B4").values = [["Source: Alibaba Group official annual results and financial reports; adjusted EBITA and free cash flow are company-defined non-GAAP measures."]];

const cardCells = ["B5", "F5", "J5", "N5", "B10", "F10", "J10", "N10"];
const valueCells = ["B6", "F6", "J6", "N6", "B11", "F11", "J11", "N11"];
const priorDeltaCells = ["B8", "F8", "J8", "N8", "B13", "F13", "J13", "N13"];
const baseDeltaCells = ["D8", "H8", "L8", "P8", "D13", "H13", "L13", "P13"];
const priorLabelCells = ["C8", "G8", "K8", "O8", "C13", "G13", "K13", "O13"];
const baseLabelCells = ["E8", "I8", "M8", "Q8", "E13", "I13", "M13", "Q13"];
const cardLabels = [
  "REVENUE (RMB BN)",
  "OPERATING INCOME (RMB BN)",
  "OPERATING MARGIN",
  "ADJUSTED EBITA (RMB BN)",
  "NET INCOME (RMB BN)",
  "OPERATING CASH FLOW (RMB BN)",
  "FREE CASH FLOW (RMB BN)",
  "CASH & LIQUID INVESTMENTS (RMB BN)",
];
for (let i = 0; i < 8; i += 1) {
  const helperRow = 2 + i;
  const cardStartCol = ["B", "F", "J", "N", "B", "F", "J", "N"][i];
  const cardEndCol = ["E", "I", "M", "Q", "E", "I", "M", "Q"][i];
  const cardRow = i < 4 ? 5 : 10;
  dashboard.getRange(`${cardStartCol}${cardRow}:${cardEndCol}${cardRow}`).clear({ applyTo: "contents" });
  dashboard.getRange(cardCells[i]).values = [[cardLabels[i]]];
  dashboard.getRange(valueCells[i]).formulas = [[`='_Chart Helpers'!B${helperRow}`]];
  dashboard.getRange(priorDeltaCells[i]).formulas = [[`=IFERROR(('_Chart Helpers'!B${helperRow}-'_Chart Helpers'!C${helperRow})/ABS('_Chart Helpers'!C${helperRow}),\"\")`]];
  dashboard.getRange(baseDeltaCells[i]).formulas = [[`=IFERROR(('_Chart Helpers'!B${helperRow}-'_Chart Helpers'!D${helperRow})/ABS('_Chart Helpers'!D${helperRow}),\"\")`]];
  dashboard.getRange(priorLabelCells[i]).values = [["vs FY2025"]];
  dashboard.getRange(baseLabelCells[i]).values = [["vs FY2022"]];
  dashboard.getRange(priorDeltaCells[i]).format.numberFormat = '+0.0%;[Red]-0.0%;-';
  dashboard.getRange(baseDeltaCells[i]).format.numberFormat = '+0.0%;[Red]-0.0%;-';
  dashboard.getRange(valueCells[i]).format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
}
dashboard.getRange("J6").format.numberFormat = '0.0%;[Red](0.0%);-';

for (const range of ["B15:I15", "J15:Q15", "B29:I29", "J29:Q29", "B43:Q43", "J45:Q48", "J50:Q52"]) {
  dashboard.getRange(range).clear({ applyTo: "contents" });
}
dashboard.getRange("B15").values = [["REVENUE & NET INCOME TREND — RMB BN"]];
dashboard.getRange("J15").values = [["ADJUSTED EBITA & FREE CASH FLOW — RMB BN"]];
dashboard.getRange("B29").values = [["FY2026 EARNINGS SCALE — RMB BN"]];
dashboard.getRange("J29").values = [["FY2026 REPORTED SEGMENT REVENUE MIX"]];
dashboard.getRange("B43").values = [["FY2026 VS FY2025"]];
dashboard.getRange("B44:H44").values = [["Metric", "Goal", "FY2026", "FY2025", "Absolute Change", "Change %", "Status"]];
for (let i = 0; i < 8; i += 1) {
  const row = 45 + i;
  const helperRow = 2 + i;
  dashboard.getRange(`B${row}:H${row}`).formulas = [[
    `='_Chart Helpers'!A${helperRow}`,
    `='_Chart Helpers'!E${helperRow}`,
    `='_Chart Helpers'!B${helperRow}`,
    `='_Chart Helpers'!C${helperRow}`,
    `=D${row}-E${row}`,
    `=IFERROR(F${row}/ABS(E${row}),\"\")`,
    `='_Chart Helpers'!F${helperRow}`,
  ]];
}
dashboard.getRange("D45:F52").format.numberFormat = '#,##0.0;[Red](#,##0.0);-';
dashboard.getRange("D47:F47").format.numberFormat = '0.0%;[Red](0.0%);-';
dashboard.getRange("G45:G52").format.numberFormat = '+0.0%;[Red]-0.0%;-';
dashboard.getRange("J45").values = [["FY2026 revenue grew 3%, but operating income and adjusted EBITA fell 64% and 56%. Free cash flow turned negative as Alibaba increased investment in quick commerce, user experience, AI and cloud infrastructure."]];
dashboard.getRange("J50").values = [["Cloud Intelligence revenue grew 34% to RMB158.1bn. Segment mix is shown before unallocated items and inter-segment eliminations; it therefore does not reconcile directly to consolidated revenue."]];
dashboard.getRange("J45:Q52").format.wrapText = true;

// Rebuild the four charts against formula-backed helper ranges while preserving the template layout.
dashboard.deleteAllDrawings();
const chartBackground = "#122437";
const chartGrid = "#31475B";
const chartText = "#B8C7D9";

const revenueChart = dashboard.charts.add("line", helpers.getRange("H1:J6"));
revenueChart.setPosition("B16", "I28");
revenueChart.title = "";
revenueChart.titlePlacement = "none";
revenueChart.hasLegend = true;
revenueChart.legend = { position: "bottom", textStyle: { fontSize: 9, fill: chartText } };
revenueChart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 9, fill: chartText }, line: { fill: chartGrid, style: "solid", width: 1 } };
revenueChart.yAxis = { numberFormatCode: '#,##0', textStyle: { fontSize: 9, fill: chartText }, majorGridlines: { fill: chartGrid, style: "solid", width: 1 } };
revenueChart.chartFill = { type: "solid", color: chartBackground };
revenueChart.plotAreaFill = { type: "solid", color: chartBackground };
if (revenueChart.series.items[0]) revenueChart.series.items[0].fill = "#28C7D9";
if (revenueChart.series.items[1]) revenueChart.series.items[1].fill = "#FFB020";

const cashChart = dashboard.charts.add("line", helpers.getRange("L1:N6"));
cashChart.setPosition("J16", "Q28");
cashChart.title = "";
cashChart.titlePlacement = "none";
cashChart.hasLegend = true;
cashChart.legend = { position: "bottom", textStyle: { fontSize: 9, fill: chartText } };
cashChart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 9, fill: chartText }, line: { fill: chartGrid, style: "solid", width: 1 } };
cashChart.yAxis = { numberFormatCode: '#,##0', textStyle: { fontSize: 9, fill: chartText }, majorGridlines: { fill: chartGrid, style: "solid", width: 1 }, crosses: "autoZero" };
cashChart.chartFill = { type: "solid", color: chartBackground };
cashChart.plotAreaFill = { type: "solid", color: chartBackground };
if (cashChart.series.items[0]) cashChart.series.items[0].fill = "#28C7D9";
if (cashChart.series.items[1]) cashChart.series.items[1].fill = "#FF6B4A";

const earningsChart = dashboard.charts.add("bar", helpers.getRange("P1:Q6"));
earningsChart.setPosition("B30", "I41");
earningsChart.title = "";
earningsChart.titlePlacement = "none";
earningsChart.hasLegend = false;
earningsChart.xAxis = { textStyle: { fontSize: 9, fill: chartText }, line: { fill: chartGrid, style: "solid", width: 1 } };
earningsChart.yAxis = { numberFormatCode: '#,##0', textStyle: { fontSize: 9, fill: chartText }, majorGridlines: { fill: chartGrid, style: "solid", width: 1 } };
earningsChart.chartFill = { type: "solid", color: chartBackground };
earningsChart.plotAreaFill = { type: "solid", color: chartBackground };
if (earningsChart.series.items[0]) earningsChart.series.items[0].fill = "#28C7D9";

const segmentChart = dashboard.charts.add("doughnut", helpers.getRange("S1:T5"));
segmentChart.setPosition("J30", "Q41");
segmentChart.title = "";
segmentChart.titlePlacement = "none";
segmentChart.hasLegend = true;
segmentChart.legend = { position: "bottom", textStyle: { fontSize: 8, fill: chartText } };
segmentChart.chartFill = { type: "solid", color: chartBackground };
segmentChart.plotAreaFill = { type: "solid", color: chartBackground };

await fs.mkdir(outputDir, { recursive: true });

const keyCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Dashboard",
  range: "A1:Q52",
  include: "values,formulas",
  tableMaxRows: 52,
  tableMaxCols: 17,
  maxChars: 14000,
});
console.log(keyCheck.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

for (const [sheetName, range, fileName] of [
  ["Dashboard", "A1:Q52", "dashboard.png"],
  ["Data & Targets", "A1:P35", "data-targets.png"],
  ["_Chart Helpers", "A1:T13", "chart-helpers.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.25, format: "png" });
  await fs.writeFile(`${workDir}/${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT ${outputPath}`);
