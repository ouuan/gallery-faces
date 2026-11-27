import { test, expect } from "@playwright/test";
test("gallery responsive states and transactional person groups", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const width of [390, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "照片库", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("这里还没有照片")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `/tmp/gallery-faces/gallery-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  await page.getByRole("checkbox", { name: "包含无人脸图片" }).click();
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page).toHaveURL(/include_no_faces=true/);
  await page.reload();
  await expect(page).toHaveURL(/include_no_faces=true/);
  await page.goto("/admin/people");
  await page.getByPlaceholder("输入管理员密码").fill("test-password");
  await page.getByRole("button", { name: "登录工作台" }).click();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "添加人物", exact: true }).click();
  await page.getByPlaceholder("输入主姓名").click();
  await expect(page.getByPlaceholder("输入主姓名")).toBeFocused();
  await page.getByPlaceholder("输入主姓名").fill("测试人物 " + Date.now());
  await page.getByPlaceholder("未填写时使用原名").fill("テスト人物");
  await page.getByPlaceholder("新分组名称").fill("  测试分组  ");
  await page.getByPlaceholder("新分组日语名称（可选）").fill("テスト組");
  await page.getByRole("button", { name: "新建分组", exact: true }).click();
  await page.getByPlaceholder("新分组名称").fill("第二组");
  await page.getByPlaceholder("新分组日语名称（可选）").fill("二組");
  await page.getByRole("button", { name: "保存人物", exact: true }).click();
  await expect(page.getByText("人物已保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^测试分组 / }).click();
  await expect(page.getByText("尚不能自动匹配").first()).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const people = await (await page.request.get("/api/v1/people")).json();
  expect(people).toContainEqual(expect.objectContaining({
    name_ja: "テスト人物",
    groups: expect.arrayContaining([
      expect.objectContaining({ name: "测试分组", name_ja: "テスト組" }),
      expect.objectContaining({ name: "第二组", name_ja: "二組" }),
    ]),
  }));
  await page.getByRole("button", { name: "分组", exact: true }).click();
  await page.locator(".person-row").filter({ hasText: "测试分组" }).getByRole("button", { name: "编辑成员" }).click();
  const fields = page.getByRole("dialog").getByRole("textbox");
  await expect(fields.nth(0)).toHaveValue("测试分组");
  await expect(fields.nth(1)).toHaveValue("テスト組");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "人物", exact: true }).click();
  await page.screenshot({
    path: "/tmp/gallery-faces/people-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "添加人物", exact: true }).click();
  await page.getByPlaceholder("新分组名称").fill("取消不创建");
  await page.getByRole("button", { name: "新建分组", exact: true }).click();
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await dialog.getByRole("button", { name: "确认", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "取消", exact: true }).click();
  const groups = await page.request.get("/api/v1/groups");
  expect((await groups.json()).some((g: any) => g.name === "取消不创建")).toBe(
    false,
  );
  await page.evaluate(() => localStorage.setItem("theme", "dark"));
  await page.reload();
  await expect(
    page.getByRole("button", { name: "添加人物", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/gallery-faces/people-dark.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("photo layouts, source text, keyboard close and error recovery", async ({
  page,
}) => {
  const source = {
    id: 1,
    post_id: 1,
    platform: "x",
    author: "fixture_author",
    published_at: "2026-01-01T00:00:00Z",
    url: "https://x.com/fixture_author/status/1",
    post_text:
      "测试正文\n保留换行 🐈 https://example.com\n<script>alert(1)</script>",
  };
  const photos = [1, 2, 3, 4, 5, 6].map((id) => ({
    id,
    image_id: id,
    image_url: `/api/v1/media/by-hash/image/${id}`,
    thumbnail_url: `/api/v1/media/by-hash/thumbnail/${id}`,
    download_url: `/api/v1/media/by-hash/original/${id}`,
    width: id % 2 ? 800 : 600,
    height: id % 2 ? 600 : 800,
    people: [{ id: 1, name: "测试人物" }],
    source_count: 2,
    matched_source: source,
  }));
  let broken = false;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("/media/"))
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#d9e1e9"/><circle cx="400" cy="250" r="120" fill="#8799aa"/><text x="400" y="480" text-anchor="middle" fill="#20242b" font-size="36">Layout test fixture</text></svg>',
      });
    if (url.pathname.endsWith("/site"))
      return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    if (url.pathname.endsWith("/people") || url.pathname.endsWith("/groups"))
      return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/gallery"))
      return broken
        ? route.fulfill({ status: 503, json: { detail: "测试网络错误" } })
        : route.fulfill({ json: { items: photos, next_cursor: null } });
    const id = Number(url.pathname.split("/").pop());
    return route.fulfill({
      json: {
        ...photos[id - 1],
        matched_source: source,
        earliest_source: source,
        sources: [
          source,
          {
            ...source,
            id: 2,
            author: "second_author",
            post_text: "另一来源自己的正文",
          },
        ],
        members: [],
      },
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator(".photo-card")).toHaveCount(6);
  await page.screenshot({
    path: "/tmp/gallery-faces/photos-desktop.png",
    fullPage: true,
  });
  await page.locator(".photo-card").first().click();
  await expect(page.getByRole("dialog", { name: "照片详情" })).toBeVisible();
  await expect(page.getByRole("button", { name: "全部来源" })).toHaveCount(0);
  await expect(page.getByText("另一来源自己的正文")).toBeVisible();
  await expect(page.locator(".post-text script")).toHaveCount(0);
  for (const width of [390, 900, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("button", { name: "放大", exact: true }).click();
    const image = page.locator(".detail-image img");
    const viewport = page.locator(".detail-image");
    await viewport.evaluate((element) => element.scrollTo(0, 0));
    const start = await image.boundingBox();
    const bounds = await viewport.boundingBox();
    expect(start!.x).toBeGreaterThanOrEqual(bounds!.x);
    expect(start!.y).toBeGreaterThanOrEqual(bounds!.y);
    await viewport.evaluate((element) =>
      element.scrollTo(element.scrollWidth, element.scrollHeight),
    );
    const end = await image.boundingBox();
    expect(end!.x + end!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width + 1);
    expect(end!.y + end!.height).toBeLessThanOrEqual(bounds!.y + bounds!.height + 1);
    await page.getByRole("button", { name: "缩小", exact: true }).click();
    await page.screenshot({
      path: `/tmp/gallery-faces/polish-detail-${width}.png`,
      animations: "disabled",
    });
  }
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/photo=2/);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/gallery-faces/photos-mobile.png",
    fullPage: true,
  });
  await page.evaluate(() => localStorage.setItem("theme", "dark"));
  await page.reload();
  await expect(page.locator(".photo-card")).toHaveCount(6);
  await page.screenshot({
    path: "/tmp/gallery-faces/photos-dark.png",
    fullPage: true,
  });
  broken = true;
  await page.reload();
  await expect(page.getByText("测试网络错误")).toBeVisible();
  broken = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.locator(".photo-card")).toHaveCount(6);
});

test("site title saves, persists publicly and fits mobile headers", async ({
  page,
}) => {
  await page.goto("/admin/settings");
  await page.getByPlaceholder("输入管理员密码").fill("test-password");
  await page.getByRole("button", { name: "登录工作台" }).click();
  const input = page.getByRole("textbox", { name: "站点标题", exact: true });
  const save = page.getByRole("button", { name: "保存设置", exact: true });
  await expect(input).toBeVisible();
  const original = await input.inputValue();
  const current = await (
    await page.request.get("/api/v1/admin/settings")
  ).json();
  const headers = { "X-Gallery-Request": "1" };
  try {
    await input.fill("   ");
    await expect(save).toBeDisabled();
    const invalid = await page.request.put("/api/v1/admin/settings", {
      headers,
      data: { ...current, site_title: "   " },
    });
    expect(invalid.status()).toBe(400);
    const tooLong = await page.request.put("/api/v1/admin/settings", {
      headers,
      data: { ...current, site_title: "标".repeat(101) },
    });
    expect(tooLong.status()).toBe(422);
    const title = "照片收藏 · " + "旅行与朋友".repeat(8);
    await input.fill(`  ${title}  `);
    await save.click();
    await expect(page.locator(".brand")).toHaveText(title);
    await expect(page).toHaveTitle(`${title} · 设置`);
    await page.reload();
    await expect(input).toHaveValue(title);
    // Older clients saving other settings must preserve a configured title.
    const legacy = { ...current };
    delete legacy.site_title;
    expect(
      (
        await page.request.put("/api/v1/admin/settings", {
          headers,
          data: legacy,
        })
      ).ok(),
    ).toBe(true);
    await page.context().clearCookies();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator(".brand")).toHaveText(title);
    await expect(page).toHaveTitle(`${title} · 照片库`);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: "/tmp/gallery-faces/site-title-mobile.png",
      fullPage: true,
    });
    await page.goto("/admin/settings");
    await expect(
      page.getByRole("heading", { name: "管理员登录" }),
    ).toBeVisible();
    await expect(page.locator(".brand")).toHaveText(title);
  } finally {
    await page.request.post("/api/v1/login", {
      data: { password: "test-password" },
    });
    await page.request.put("/api/v1/admin/settings", {
      headers,
      data: { ...current, site_title: original },
    });
  }
});

test("publisher names, cross-platform selector and single-source links", async ({
  page,
}) => {
  const source = {
    id: 1,
    post_id: 1,
    platform: "x",
    author: "alice",
    author_name: "账号昵称",
    published_at: "2026-01-01T00:00:00Z",
    url: "https://x.com/alice/status/1",
    coauthors: [{ username: "bob", full_name: "共同作者" }],
  };
  const person = {
    id: 7,
    name: "关联人物",
    groups: [],
    accounts: [
      { platform: "x", username: "alice" },
      { platform: "instagram", username: "alice_ig" },
    ],
    reference_count: 0,
    avatar_image_id: null,
  };
  const photo = {
    id: 1,
    image_id: 1,
    image_url: "/api/v1/media/by-hash/image/1",
    thumbnail_url: "/api/v1/media/by-hash/thumbnail/1",
    download_url: "/api/v1/media/by-hash/original/1",
    width: 800,
    height: 600,
    people: [],
    source_count: 1,
    matched_source: source,
  };
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes("/media/"))
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#d9e1e9"/></svg>',
      });
    if (url.pathname.endsWith("/site"))
      return route.fulfill({
        json: { timezone: "Asia/Shanghai", site_title: "Gallery Faces" },
      });
    if (url.pathname.endsWith("/people"))
      return route.fulfill({ json: [person] });
    if (url.pathname.endsWith("/groups")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/gallery"))
      return route.fulfill({ json: { items: [photo], next_cursor: null } });
    return route.fulfill({
      json: {
        ...photo,
        sources: [source],
        earliest_source: source,
        members: [],
      },
    });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect(page.locator(".photo-meta")).toContainText("关联人物");
  await page
    .getByRole("group", { name: "发布者", exact: true })
    .locator(".n-base-selection")
    .first()
    .click();
  await page
    .locator(".n-cascader-option__label")
    .filter({ hasText: /^未分组$/ })
    .click();
  await page
    .locator(".n-cascader-option__label")
    .filter({ hasText: /^关联人物$/ })
    .click();
  await expect(page).toHaveURL(/publishers=person(?::|%3A)7/);
  await page.reload();
  await expect(
    page
      .getByRole("group", { name: "发布者", exact: true })
      .locator(".n-base-selection-tags"),
  ).toContainText("未分组");
  await page.locator(".photo-card").click();
  const dialog = page.getByRole("dialog", { name: "照片详情" });
  await expect(dialog.getByText("X · 关联人物", { exact: true })).toBeVisible();
  await expect(dialog.getByText("共同作者 (@bob)", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "X · 关联人物", exact: true })).toHaveCount(1);
  await expect(
    dialog.getByRole("link", { name: "查看来源（最早收录帖子）" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "/tmp/gallery-faces/publisher-detail.png",
    animations: "disabled",
  });
  person.accounts = [];
  await page.reload();
  await expect(dialog.getByText("X · 账号昵称", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/gallery-faces/publisher-detail-mobile.png",
    animations: "disabled",
  });
});

test("filters omit avatars and people management uses reference face crops", async ({
  page,
}) => {
  const people = [
    {
      id: 1,
      name: "有参考图",
      groups: [],
      accounts: [],
      reference_count: 1,
      avatar_reference_id: 9,
    },
    {
      id: 2,
      name: "暂无参考图人物",
      groups: [],
      accounts: [],
      reference_count: 0,
      avatar_reference_id: null,
    },
  ];
  let avatarFailed = false;
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/references/9/crop"))
      return avatarFailed
        ? route.fulfill({ status: 404, json: { detail: "图片不存在" } })
        : route.fulfill({
            contentType: "image/svg+xml",
            body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="30"><rect width="20" height="30" fill="#8799aa"/></svg>',
          });
    if (path.endsWith("/people")) return route.fulfill({ json: people });
    if (path.endsWith("/site"))
      return route.fulfill({
        json: { timezone: "Asia/Shanghai", site_title: "Gallery Faces" },
      });
    if (path.endsWith("/gallery"))
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/session")) return route.fulfill({ json: { ok: true } });
    if (path.endsWith("/settings"))
      return route.fulfill({ json: { cookies: {} } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page.locator(".people-cascader")).toBeVisible();
  await expect(page.locator(".filters img, .filters .avatar")).toHaveCount(0);
  await page.goto("/admin/people");
  await page.getByRole("button", { name: /^未分组 / }).click();
  const avatar = page.getByRole("img", { name: "有参考图的参考人脸" });
  await expect(avatar).toHaveAttribute(
    "src",
    "/api/v1/admin/references/9/crop",
  );
  await expect
    .poll(() => avatar.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(20);
  await expect(
    page.getByRole("img", { name: "暂无参考图", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/gallery-faces/reference-avatar-desktop.png",
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/gallery-faces/reference-avatar-mobile.png",
    animations: "disabled",
  });
  avatarFailed = true;
  await page.reload();
  await page.getByRole("button", { name: /^未分组 / }).click();
  await expect(page.getByRole("img", { name: "参考图无法加载" })).toBeVisible();
});

test("delete current or selected images with cancel and failure recovery", async ({
  page,
}) => {
  let images = [1, 2, 3].map((id) => ({
    id,
    width: 100,
    height: 100,
    faces: [],
    sources: [],
  }));
  const deleted: number[][] = [];
  let failNext = true;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/admin/media/"))
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="#8799aa"/></svg>',
      });
    if (path.endsWith("/images/recycle-preview")) {
      const { ids } = route.request().postDataJSON();
      return route.fulfill({ json: { ids, total: ids.length, groups: ids.length, already_trashed: 0, scope_token: "test-scope" } });
    }
    if (path.endsWith("/images/actions")) {
      const body = route.request().postDataJSON();
      expect(body.action).toBe("delete");
      if (failNext) {
        failNext = false;
        return route.fulfill({
          status: 409,
          json: { detail: "图片处理任务正在运行，请稍后重试" },
        });
      }
      deleted.push(body.ids);
      images = images.filter((image) => !body.ids.includes(image.id));
      return route.fulfill({
        json: { deleted: body.ids.length, ids: body.ids, cleanup_pending: 0 },
      });
    }
    if (path.endsWith("/images")) {
      expect(new URL(route.request().url()).searchParams.get("state")).toBe("review");
      return route.fulfill({ json: images });
    }
    if (path.endsWith("/site"))
      return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    if (path.endsWith("/session")) return route.fulfill({ json: { ok: true } });
    if (path.endsWith("/settings"))
      return route.fulfill({ json: { cookies: {} } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review");
  await expect(page.locator('.review-toolbar')).toContainText('全部待审核');
  await expect(
    page.getByRole("button", { name: "将当前图片移入回收站", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "图片 #1 · 共 1 个版本", exact: true }),
  ).toBeVisible();
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await dialog.getByRole("button", { name: "取消", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "将当前图片移入回收站", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(deleted).toHaveLength(0);
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await expect(dialog).toContainText("包含所选图片的所有重复版本"); await dialog.getByRole("button", { name: "确认", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "将当前图片移入回收站", exact: true }).click();
  await expect(
    page.getByText("图片处理任务正在运行，请稍后重试"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "图片 #1 · 共 1 个版本", exact: true }),
  ).toBeVisible();
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await dialog.getByRole("button", { name: "确认", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "将当前图片移入回收站", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "图片 #2 · 共 1 个版本", exact: true }),
  ).toBeVisible();
  expect(deleted).toEqual([[1]]);
  await page.getByRole("checkbox", { name: "选择图片（2）", exact: true }).click();
  await page.getByRole("checkbox", { name: "选择图片（3）", exact: true }).click();
  await expect(page.getByText("已选 2 张", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/gallery-faces/delete-images-mobile.png",
    animations: "disabled",
    fullPage: true,
  });
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await expect(dialog).toContainText("2 张图片"); await dialog.getByRole("button", { name: "确认", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "将所选图片及所有重复版本移入回收站", exact: true }).click();
  await expect(page.getByText("没有需要处理的照片")).toBeVisible();
  expect(deleted).toEqual([[1], [2, 3]]);
  for (const name of ["重新检测", "将当前图片移入回收站"])
    await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
});

test("people cascader groups, shared members, search and mobile apply", async ({
  page,
}) => {
  const groups = [
    { id: 1, name: "朋友" },
    { id: 2, name: "同事" },
  ];
  const people = [
    { id: 1, name: "共同成员", groups },
    { id: 2, name: "朋友甲", groups: [groups[0]] },
    { id: 3, name: "同事乙", groups: [groups[1]] },
    { id: 4, name: "独立人物", groups: [] },
  ].map((person) => ({
    ...person,
    accounts: [],
    reference_count: 0,
    avatar_reference_id: null,
  }));
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/people")) return route.fulfill({ json: people });
    if (path.endsWith("/groups")) return route.fulfill({ json: groups });
    if (path.endsWith("/site"))
      return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const picker = page.locator(".desktop-filters .people-cascader");
  await picker.locator(".n-base-selection").click();
  const option = (text: string) =>
    page
      .locator(".people-cascader-menu .n-cascader-option")
      .filter({
        has: page.locator(".n-cascader-option__label", {
          hasText: new RegExp("^" + text + "$"),
        }),
      });
  await picker.locator("input").fill("共同");
  const shared = page.locator(".people-cascader-search:visible .n-base-select-option");
  await expect(shared).toHaveCount(1);
  await shared.click();
  await expect(picker.locator(".n-tag")).toHaveText(["共同成员"]);
  await expect.poll(() => new URL(page.url()).searchParams.get("people")).toBe("1");
  await option("朋友").locator(".n-checkbox").click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe("1-2");
  await option("同事").locator(".n-cascader-option__label").click();
  await expect(option("共同成员").getByRole("checkbox")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await option("共同成员").click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe("2");
  await picker.locator("input").fill("独立");
  await page
    .locator(".people-cascader-search .n-base-select-option")
    .filter({ hasText: "独立人物" })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe("2,4");
  await page.getByRole("heading", { name: "照片库", exact: true }).click();
  const modes = page.locator('.desktop-filters [aria-label="人物匹配方式"]');
  const others = page.locator('.desktop-filters [aria-label="是否包含其他人物"]');
  await expect(modes.locator(".n-radio-button")).toHaveText(["任一入镜", "全部同框"]);
  await expect(others.locator(".n-radio-button")).toHaveText(["仅限所选", "可含他人"]);
  await modes.getByText("全部同框").click();
  await expect(page).toHaveURL(/match=all/);
  await others.getByText("仅限所选").click();
  await expect(page).toHaveURL(/match=exact/);
  await modes.getByText("任一入镜").click();
  await expect(page).toHaveURL(/match=subset/);
  await page.reload();
  await expect(others.getByRole("radio", { name: "仅限所选" })).toBeChecked();
  await expect(modes.getByRole("radio", { name: "任一入镜" })).toBeChecked();
  await expect(picker).toContainText("朋友甲");
  await expect(picker).toContainText("未分组");
  await expect(picker.locator(".n-tag")).toHaveText(["朋友甲", "未分组"]);
  await picker.locator(".n-base-selection").click();
  await option("朋友").locator(".n-cascader-option__label").click();
  await expect(option("朋友甲").getByRole("checkbox")).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.screenshot({
    path: "/tmp/gallery-faces/cascader-desktop.png",
    animations: "disabled",
  });
  await page.getByRole("heading", { name: "照片库", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  const mobile = page.locator(".n-drawer .people-cascader");
  await mobile.locator(".n-base-selection").click({ position: { x: 8, y: 8 } });
  await option("同事").locator(".n-checkbox").click();
  await option("同事").locator(".n-cascader-option__label").click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe("2,4");
  await page.screenshot({
    path: "/tmp/gallery-faces/cascader-mobile.png",
    animations: "disabled",
  });
  const bounds = await page
    .locator(".people-cascader-menu:visible")
    .boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe("1-4");
  await page.reload();
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  await page
    .locator(".n-drawer")
    .getByRole("button", { name: "清空", exact: true })
    .click();
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBeNull();
});

test("publisher cascader groups, unlinked accounts and mobile apply", async ({ page }) => {
  let candidateRequests = 0;
  const groups = [{ id: 1, name: "朋友" }, { id: 2, name: "同事" }];
  const people = [
    { id: 1, name: "共同成员", groups, accounts: [{ platform: "x", username: "shared" }] },
    { id: 2, name: "朋友甲", groups: [groups[0]], accounts: [{ platform: "instagram", username: "friend" }] },
    { id: 3, name: "没有账号", groups, accounts: [] },
  ];
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/people")) return route.fulfill({ json: people });
    if (path.endsWith("/groups")) return route.fulfill({ json: groups });
    if (path.endsWith("/publisher-candidates")) {
      candidateRequests++;
      return route.fulfill({ json: [
      { platform: "x", username: "unlinked", label: "未关联昵称" },
      { platform: "x", username: "shared", label: "不应重复显示" },
      ] });
    }
    if (path.endsWith("/site")) return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const picker = page.locator(".desktop-filters .publisher-cascader");
  await expect(page.getByRole("button", { name: "添加发布者", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("发布者用户名", { exact: true })).toHaveCount(0);
  const option = (label: string) => page.locator(".people-cascader-menu:visible .n-cascader-option")
    .filter({ has: page.locator(".n-cascader-option__label", { hasText: new RegExp(`^${label}$`) }) });
  const selected = () => new URL(page.url()).searchParams.get("publishers")?.split(",").sort();
  expect(candidateRequests).toBe(0);
  await picker.locator(".n-base-selection").click();
  await expect.poll(() => candidateRequests).toBe(1);
  await option("朋友").locator(".n-checkbox").click();
  await expect.poll(selected).toEqual(["person:1-2"]);
  await option("其他").locator(".n-cascader-option__label").click();
  await expect(option("未关联昵称 · X")).toHaveCount(1);
  await option("其他").locator(".n-checkbox").click();
  await expect.poll(selected).toEqual(["person:1-2", "x:unlinked"]);
  await expect(option("不应重复显示 · X")).toHaveCount(0);
  await page.screenshot({ path: "/tmp/gallery-faces/publisher-other-desktop.png", animations: "disabled" });
  await option("同事").locator(".n-cascader-option__label").click();
  await expect(option("共同成员").getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
  await expect(option("没有账号")).toHaveCount(0);
  await option("共同成员").click();
  await expect.poll(selected).toEqual(["person:2", "x:unlinked"]);
  await picker.locator("input").fill("共同");
  const shared = page.locator(".people-cascader-search:visible .n-base-select-option");
  await expect(shared).toHaveCount(1);
  await shared.click();
  await expect.poll(selected).toEqual(["person:1-2", "x:unlinked"]);
  await page.getByRole("heading", { name: "照片库", exact: true }).click();
  await page.reload();
  await picker.locator(".n-base-selection").click();
  await option("朋友").locator(".n-cascader-option__label").click();
  await expect(option("朋友甲").getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
  await page.screenshot({ path: "/tmp/gallery-faces/publisher-cascader-desktop.png", animations: "disabled" });
  await page.getByRole("heading", { name: "照片库", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  const mobile = page.locator(".n-drawer .publisher-cascader");
  await mobile.locator(".n-base-selection").click();
  await option("同事").locator(".n-cascader-option__label").click();
  await option("共同成员").click();
  await expect.poll(selected).toEqual(["person:1-2", "x:unlinked"]);
  await option("其他").locator(".n-cascader-option__label").click();
  await page.screenshot({ path: "/tmp/gallery-faces/publisher-cascader-mobile.png", animations: "disabled" });
  const bounds = await page.locator(".people-cascader-menu:visible").boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect.poll(selected).toEqual(["person:2", "x:unlinked"]);
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  await mobile.hover();
  await mobile.locator(".n-base-clear").click();
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("publishers")).toBeNull();
});
