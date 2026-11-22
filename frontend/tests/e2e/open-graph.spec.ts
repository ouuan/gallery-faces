import { test, expect } from "@playwright/test";

test("sharing settings save independently for both frontends and can be cleared", async ({ page }) => {
  let settings: Record<string, any> = {
    site_title: "Gallery Faces", detection_threshold: "0.5", threshold: "0.5", margin: "0.1",
    phash_distance: "4", aspect_tolerance: "0.01", ssim_threshold: "0.98", review_ssim_threshold: "0.5",
    og_title: "", og_description: "", og_image: "", og_url: "",
    og_title_ja: "", og_description_ja: "", og_image_ja: "", og_url_ja: "",
    cookies: {}, models_ready: true,
  };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: settings.site_title } });
    if (path.endsWith("/admin/settings")) {
      if (route.request().method() === "PUT") {
        settings = route.request().postDataJSON();
        return route.fulfill({ json: { ok: true } });
      }
      return route.fulfill({ json: settings });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/settings");
  await page.getByRole('textbox', { name: 'Agent 审核规则' }).fill('只建议有可核实依据的匹配。');
  for (const [label, suffix] of [["中文前端", ""], ["日语只读前端", "_ja"]]) {
    await page.getByRole("textbox", { name: label + "分享标题", exact: true }).fill(label + "分享");
    await page.getByRole("textbox", { name: label + "分享描述", exact: true }).fill(label + "说明");
    await page.getByRole("textbox", { name: label + "预览图 URL", exact: true }).fill(`https://example.com/share${suffix}.jpg`);
    await page.getByRole("textbox", { name: label + "站点 URL", exact: true }).fill(`https://example.com/${suffix}`);
  }
  const save = page.getByRole("button", { name: "保存设置", exact: true });
  await save.click();
  await expect.poll(() => settings.og_title_ja).toBe("日语只读前端分享");
  expect(settings.og_title).toBe("中文前端分享");
  expect(settings.og_image_ja).toBe("https://example.com/share_ja.jpg");
  expect(settings.og_description).toBe("中文前端说明");
  expect(settings.og_url).toBe("https://example.com/");
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => localStorage.setItem("theme", theme), theme);
      await page.reload();
      await expect(page.getByRole('textbox', { name: 'Agent 审核规则' })).toHaveValue('只建议有可核实依据的匹配。');
      await expect(page.getByRole("textbox", { name: "中文前端分享标题", exact: true })).toHaveValue("中文前端分享");
      await expect(page.getByRole("textbox", { name: "日语只读前端分享标题", exact: true })).toHaveValue("日语只读前端分享");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `/tmp/gallery-faces/open-graph-${width}-${theme}.png`, fullPage: true });
    }
  }
  for (const name of ["分享标题", "分享描述", "预览图 URL", "站点 URL"]) {
    await page.getByRole("textbox", { name: "中文前端" + name, exact: true }).fill("");
  }
  await save.click();
  await expect.poll(() => settings.og_title).toBe("");
  expect(settings.og_description).toBe("");
  expect(settings.og_image).toBe("");
  expect(settings.og_url).toBe("");
  expect(settings.og_title_ja).toBe("日语只读前端分享");
});
