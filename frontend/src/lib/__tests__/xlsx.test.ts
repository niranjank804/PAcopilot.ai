import { strFromU8, unzipSync } from "fflate";
import { describe, expect, it } from "vitest";

import { buildXlsx, columnName, sheetName } from "../xlsx";

function sheet(bytes: Uint8Array): string {
  return strFromU8(unzipSync(bytes)["xl/worksheets/sheet1.xml"]);
}

describe("xlsx", () => {
  it("names columns past Z", () => {
    expect([0, 25, 26, 701, 702].map(columnName)).toEqual(["A", "Z", "AA", "ZZ", "AAA"]);
  });

  it("keeps sheet names within Excel's rules", () => {
    expect(sheetName("Sales [2026]: a/b")).toBe("Sales  2026   a b");
    expect(sheetName("x".repeat(40))).toHaveLength(31);
    expect(sheetName("  ")).toBe("Sheet1");
  });

  it("writes a workbook Excel can open: header bold, numbers numeric, text escaped", () => {
    const bytes = buildXlsx(
      [
        ["Period", "1:USA MGR", "R&D <x>"],
        ["Q1 2025", 132_998_441, 6492.98],
        ["Q2 2025", null, "n/a"],
      ],
      "Workforce Planning Summary",
    );
    const files = unzipSync(bytes);
    expect(Object.keys(files).sort()).toEqual([
      "[Content_Types].xml",
      "_rels/.rels",
      "xl/_rels/workbook.xml.rels",
      "xl/styles.xml",
      "xl/workbook.xml",
      "xl/worksheets/sheet1.xml",
    ]);
    const xml = sheet(bytes);
    expect(xml).toContain('<c r="A1" t="inlineStr" s="1">');
    expect(xml).toContain("R&amp;D &lt;x&gt;");
    // Whole numbers get "#,##0", decimals "#,##0.00"; both stay numbers.
    expect(xml).toContain('<c r="B2" s="2"><v>132998441</v></c>');
    expect(xml).toContain('<c r="C2" s="3"><v>6492.98</v></c>');
    // Empty cells are left out, not written as zero.
    expect(xml).not.toContain('r="B3"');
    // Columns are wide enough for "132,998,441"; the header row is frozen.
    expect(xml).toMatch(/<col min="2" max="2" width="13"/);
    expect(xml).toContain('state="frozen"');
    expect(strFromU8(files["xl/workbook.xml"])).toContain('name="Workforce Planning Summary"');
  });
});
