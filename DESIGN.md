---
name: Gallery Faces
description: 照片档案馆：让照片与来源清晰可见，让整理工具克制而易用。
colors:
  bg: '#f6f7f9'
  panel: '#fff'
  text: '#20242b'
  muted: '#5c6470'
  line: '#dce1e7'
  accent: '#245ec7'
  selection: '#e5edfc'
  bg-dark: '#17191d'
  panel-dark: '#22262c'
  text-dark: '#edf0f4'
  muted-dark: '#b4bdc9'
  line-dark: '#424a56'
  accent-dark: '#85adff'
  selection-dark: '#263b60'
  error-text: '#bd3b3b'
  error-text-dark: '#ff9292'
  placeholder: '#68717d'
  placeholder-dark: '#a0a9b5'
  accent-hover: '#1e50ab'
  accent-pressed: '#19438f'
  accent-hover-dark: '#a3c1ff'
  accent-pressed-dark: '#6994e8'
  on-primary: '#fff'
  on-primary-dark: '#000'
typography:
  title:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: -0.02em
  heading:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 19px
    fontWeight: 700
    lineHeight: 1.6
  section-label:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.6
  subheading:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 15px
    fontWeight: 700
    lineHeight: 1.6
  body:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  paragraph:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 550
    lineHeight: 1.6
  hint:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
  photo-caption:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.6
  photo-caption-mobile:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.6
  photo-title:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 550
    lineHeight: 1.6
  photo-title-mobile:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 13px
    fontWeight: 550
    lineHeight: 1.6
  button:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe
      UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1
rounded:
  tag: 2px
  photo: 4px
  control: 6px
  container: 8px
spacing:
  '4': 4px
  '6': 6px
  '8': 8px
  '10': 10px
  '12': 12px
  '16': 16px
  '20': 20px
  '24': 24px
  '28': 28px
  '32': 32px
  '36': 36px
components:
  button-primary:
    backgroundColor: '{colors.accent}'
    textColor: '{colors.on-primary}'
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    height: 44px
    padding: 0px 14px
  button-default:
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    height: 44px
    padding: 0px 14px
  button-text:
    textColor: '{colors.accent}'
    typography: '{typography.body}'
    padding: 8px 0px
  input:
    rounded: '{rounded.control}'
    height: 44px
    typography: '{typography.body}'
  tag:
    rounded: '{rounded.tag}'
    height: 28px
    typography: '{typography.body}'
  nav-item:
    textColor: '{colors.muted}'
    rounded: '{rounded.control}'
    padding: 12px
  nav-item-selected:
    textColor: '{colors.accent}'
    backgroundColor: '{colors.selection}'
    rounded: '{rounded.control}'
    padding: 12px
  form-container:
    backgroundColor: '{colors.panel}'
    textColor: '{colors.text}'
    rounded: '{rounded.container}'
    padding: 8px 24px 24px
  photo-card:
    textColor: '{colors.text}'
    padding: 0px
  person-avatar:
    backgroundColor: '{colors.selection}'
    textColor: '{colors.accent}'
    width: 44px
    height: 44px
  button-primary-hover:
    backgroundColor: '{colors.accent-hover}'
  button-primary-pressed:
    backgroundColor: '{colors.accent-pressed}'
  button-primary-hover-dark:
    backgroundColor: '{colors.accent-hover-dark}'
  button-primary-pressed-dark:
    backgroundColor: '{colors.accent-pressed-dark}'
  button-primary-dark:
    backgroundColor: '{colors.accent-dark}'
    textColor: '{colors.on-primary-dark}'
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    height: 44px
    padding: 0px 14px
---

# Design System: Gallery Faces

## Overview

**Creative North Star: "照片档案馆"**

照片档案馆以照片及其来源记录为中心。中性的画布承托图像，文字保留人物、发布者与时间的线索；蓝色用于引导操作和标记选择，让浏览有秩序，也让每张照片的来处可追溯。

整理工具沿用熟悉的表单、列表和导航。组件克制、清晰、易用，管理界面紧凑但保留操作空间。系统字体、细边界和浅深主题构成持续的视觉身份，不引入装饰性渐变或营销叙事。

**Key Characteristics:**
- 照片优先，来源信息可读。
- 中性色承托内容，蓝色指示操作与选择。
- 平面为主、浮层突出。
- 中文界面，熟悉的控件与明确的状态。

本次为现有实现的记录，不是界面改版。依据 `frontend/src/style.css`、`frontend/src/App.vue`、各 Vue 组件的局部样式及 Naive UI 2.45.3 的最终渲染。基础变量以 frontmatter 为准；下文解释用途与实现差异。格式遵循 [DESIGN.md 规范](https://github.com/google-labs-code/design.md/blob/main/docs/spec.md)。

## Colors

中性色承担画布、容器和阅读层次，蓝色承担操作与选中语义。浅深主题使用相同角色，不机械反转颜色。

### Primary

操作蓝（`accent`）用于链接、主操作、焦点边界与选中项文字；选择底色（`selection`）用于文本选区、激活导航和头像占位。

**The 照片优先 Rule.** 强调色服务于操作与选择；内容区的视觉重心留给照片。

### Neutral

| 用途名称 | 浅色变量 | 深色变量 | CSS 映射 |
| --- | --- | --- | --- |
| 画布灰 | bg | bg-dark | --bg |
| 面板底色 | panel | panel-dark | --panel |
| 主要文字 | text | text-dark | --text |
| 次要文字 | muted | muted-dark | --muted |
| 分隔线 | line | line-dark | --line |
| 操作蓝 | accent | accent-dark | --accent |
| 选择底色 | selection | selection-dark | --selection |

`html[data-theme="dark"]` 切换 CSS 变量；Naive UI 同时使用 darkTheme。用户可以指定主题或跟随系统，选择保存在本地。

### 状态色与实现差异

任务错误文本通过 `--error` 使用 `error-text` 与 `error-text-dark`，适配浅深主题；NAlert 等状态组件沿用组件库主题，不把状态色当作装饰色。主按钮的文字分别使用 `on-primary` 和 `on-primary-dark`。

App 覆盖 Naive UI 的 primaryColor、primaryColorHover、primaryColorPressed 和 primaryColorSuppl。主按钮悬停及聚焦使用 `accent-hover`，按下使用 `accent-pressed`；深色主题使用对应的 `-dark` 变量。输入占位文字使用 `placeholder` 与 `placeholder-dark`。输入框背景、默认按钮文字、边框和标签等也有组件库自己的值，不保证等同于项目的 panel/text/line。

## Typography

使用系统无衬线字体及平台中文回退，没有独立展示字体或自托管字体。frontmatter 记录浏览器实际继承的字体栈；其中 v-sans 是组件库字体候选名，并不表示项目加载了此字体。

根元素字号为 15px，决定 rem 基准；Naive UI 注入的 body 样式将实际正文设为 14px，行高 1.6。App 的字体配置与最终全局继承并不完全相同，应以计算样式为准。段落另用 1.65 行高。

| 角色 | frontmatter 变量 | 使用位置 |
| --- | --- | --- |
| 页面标题 | title | h1；紧凑字距 |
| 二级标题 | heading | 常规 h2 |
| 分区标题 | section-label | 筛选与 section-heading 中的 h2 |
| 小标题 | subheading | h3 |
| 正文、段落 | body、paragraph | 通用阅读内容 |
| 表单标签 | label | 字重 550 的字段标签 |
| 提示 | hint | 提示、来源时间、审核说明 |
| 照片元信息 | photo-caption、photo-caption-mobile | 桌面与移动端分别使用 |
| 照片人物名 | photo-title、photo-title-mobile | 照片元信息中的强调文字 |
| 按钮 | button | 中号 Naive UI 按钮 |

表格为 14px，表头为 13px/550；数据与审核序号使用等宽数字特性。品牌文字桌面 18px/650，移动端 16px。来源正文保留换行，长 URL 可折行，默认截取三行并提供展开操作。

**The 按角色排字 Rule.** 以实际使用角色区分标题、正文、提示和照片元信息，不用一个字号概括所有文本。

## Layout

间距按使用频率记录，不宣称严格遵守单一倍数网格。frontmatter 收录复用的间距；图片说明还存在 3px、9px、14px 等局部细节。

- 页头固定高度 64px，吸顶；桌面横向内边距 28px，移动端 16px。
- 照片浏览默认左栏 248px、内容区自适应，内容内边距 28px。管理导航为 192px，内容最大宽度 1400px、内边距 28px 36px。
- 普通表单最大宽度 700px，设置表单 560px；表格容器可横向滚动。
- 等高排列用弹性行和原始比例计算宽度，图像 contain；默认图像高度 220px。方形布局使用 cover 裁切；瀑布流保留图像比例。默认方形与瀑布流均为三列，间隔 16px。

| 条件 | 布局行为 |
| --- | --- |
| ≤900px | 筛选栏 210px；画廊内边距 20px；工具栏纵向；769–900px 详情侧栏为 280px |
| ≤640px | 隐藏筛选侧栏，改为左侧抽屉，关闭时应用筛选；画廊和管理区内边距 24px 16px；管理导航成为可横向滚动的顶栏 |
| ≤640px | 图片两列、间隔 12px，等高图像高度 170px |
| ≤768px | 详情全屏上下排列，工具栏常驻，图片与详情整体滚动，图像区高度 55dvh；内边距适配安全区域 |
| ≥1200px | 审核图像与详情分为两栏，详情宽 336px；图像区在 top:88px 吸顶 |
| ≥1440px | 方形与瀑布流四列；等高图像高度 250px |

重复图片对比工作区占满页头以下的视口，两张图始终并排；宽度 ≤640px 或高度 ≤600px 时切换紧凑导航，高度 ≤600px 且宽度 ≥700px 时进一步压缩图注布局。

审核缩略图条始终横向滚动，这是 Review.vue 覆盖全局旧布局后的结果。审核预览根据图片比例限制在约 52dvh 的高度，窄屏先图像后详情。日期、来源和人物操作允许换行。

## Elevation & Depth

基础容器用表面色和 1px 边界区分，不添加卡片阴影。弹窗、抽屉及下拉菜单继承 Naive UI 的浮层样式，阴影与遮罩说明临时层级。照片详情实测继承组件库的三层阴影，准确值保存在 sidecar 的 shadows 中。

输入框聚焦时存在组件库光晕：浅色为细蓝色外圈，深色为蓝色柔和阴影。这是焦点反馈，不是容器装饰。常规按钮和链接的键盘焦点使用操作蓝实线轮廓（2px），外偏移 3px。

**The 平面为主 Rule.** 常驻容器通过表面色与细边框划分；浮层通过遮罩和组件库阴影建立临时层级。

动效来自组件库的按钮状态、菜单、抽屉和对话框过渡；项目没有单独编排入场动画。开启 prefers-reduced-motion 时，全局禁用 transition、animation，并取消平滑滚动。

## Shapes

照片缩略图用 photo 圆角；常规控件用 control 圆角；表单容器与桌面弹窗用 container 圆角。普通 NTag 使用组件库较小的 tag 圆角，不能概括为所有控件均使用同一圆角。

头像为圆形（50%），常规占位尺寸 28px，人物列表头像 44px；圆形百分比保留在组件预览 CSS 中。移动端照片详情取消圆角。人脸框为矩形，忽略状态用虚线和降低透明度区别。

## Components

### 按钮

克制、清晰、易用。中号主按钮与普通按钮高 44px、横向内边距 14px。主按钮用操作蓝底色；普通按钮透明底、细描边，文字和描边来自组件库。悬停、聚焦和按下态沿用 Colors 中的蓝色状态变量。禁用态降低透明度且不可操作；异步提交使用加载状态。

文字按钮透明、无边框、操作蓝文字，上下内边距 8px、最小高度 44px；审核候选按钮另有 44px 最小高度。小号工具按钮仍用组件库尺寸，因此“44px”不是所有交互元素都已满足的声明。

### 输入与人物选择

中号输入、选择器和人物级联选择器高度 44px，control 圆角。原生日期输入使用项目面板色与分隔线色。多行输入按内容和行数扩展，不固定为单行高度。

人物选择按分组展开，可搜索和清空；筛选采用多选，身份编辑采用单选。级联选项高 44px，列宽最多 180px 并按视口收缩。无人物与搜索无匹配分别提供明确文案。禁用和错误状态沿用 Naive UI，不能仅凭边框颜色推断状态。输入框悬停与聚焦边框使用操作蓝的 hover 变量；深色输入框默认透明边框，聚焦背景带操作蓝色调。

### 标签与导航

人物分组使用普通 NTag，默认高 28px、字号 14px，作为信息标签；不要为展示型标签添加交互。导航激活项使用选择底色、操作蓝文字及 600 字重；悬停时背景为画布色。桌面管理导航含图标，移动端隐藏图标并横向滚动。

### 容器与照片卡片

导入表单为面板底色、细边框和 container 圆角，桌面内边距 8px 24px 24px，移动端为 4px 16px 20px。列表用分隔线组织，不将每项包装成浮起的卡片。

照片卡片为可点击按钮，去除默认边框与内边距；悬停时仅图像亮度降至 0.94，键盘焦点可见。照片下方展示人物与来源信息；图片区域与文字不共享裁切规则。

### 抽屉、详情与表单弹窗

移动端筛选抽屉从左侧打开，宽度为 min(340px, 100vw)。修改草稿后，点击外部遮罩、按 Esc 或点击底部“应用筛选”均应用条件并关闭抽屉；“清空”仅重置草稿，关闭时生效。顶部仅保留表单中的“筛选照片／清空”一行，不显示额外标题或关闭按钮。

照片详情桌面尺寸为视口宽高各减 48px，默认来源侧栏 340px；移动端为 100vw × 100dvh。工具栏将切图和缩放／下载分组，关闭按钮靠右。桌面来源区独立滚动；人物标题下为管理员入口。来源列表以“来源 · N”为标题，各来源的“平台 · 发布者”标题附外链图标并链接到原帖，在新标签页打开；各来源的日期与尺寸使用 13px 次要文字并列，以“·”分隔，允许换行；单来源也展示尺寸，同来源相同尺寸去重，缺失时省略。来源内部主要使用 8px 间距，标题与元信息紧凑相邻，记录上下内边距为 12px，并以细线分隔。人物概况与来源列表间隔 16px，反馈区位于列表后、间隔 16px；反馈表单距标题 12px，输入框通过无障碍名称标识，不另设可见标签。表单弹窗宽度为 min(560px, 100vw - 32px)，最大高度 90dvh，可滚动，操作按钮靠右排列。弹窗保留对话框语义与焦点管理。

### 人物头像与审核

人物头像优先使用参考人脸；缺失或加载失败时显示圆形人物图标与对应无障碍名称。审核采用横向缩略图条、图片预览和身份/来源编辑；每个在库重复组显示一项，导航和选择数量按组计数，标题显示“代表图 #ID · 共 N 个版本”。人脸预览和编辑绑定代表图，组内来源与反馈标注原图片 ID，来源缺失列出待补全的成员。刷新前确认放弃草稿，保存冲突保留未提交内容。当前项有强调边框及选择底色。人脸框为操作蓝细框，忽略状态为虚线并降低透明度。

隐藏与删除统一为“移入回收站”，按当前重复组展开，确认弹窗显示组数、全部图片数量及已回收数量。审核筛选包含“回收站”和“全部在库图片”。回收站沿用横向缩略图条和预览／记录双栏，移动端改为纵向排列；只读展示保留缩略图、来源和人脸审核结果，不呈现补框或确认控件。顶部提供全选本页、单张／批量恢复、刷新及可选本地目录，底部分页。清理待重试、恢复排队／执行中、失败和取消状态分别展示；失败可重新选择目录后重试，运行中可取消。恢复按所选图片执行，不自动扩大到重复组。

### 内容状态与预览约定

空状态使用居中图标、说明和适用的恢复操作；加载使用覆盖式旋转指示器，不挤动原有布局；加载按钮保持宽度，隐藏原文字并将指示器居中。详情、审核与重复图片对比在大图加载期间先显示缩略图，保持预览空间。失败用错误提示及重试入口。文档中的预览只展示样式与原生交互，不模拟业务提交。

配套预览可在 Shadow DOM 独立呈现。它们继承项目 CSS 变量并提供浅色回退；在 shadow host 上设置 data-theme="dark" 可预览深色。八阶颜色带仅辅助查看色相与明度，不是可直接用于新界面的配色扩展。

## Do's and Don'ts

### Do:
- Do 沿用语义颜色变量，同时检查浅色与深色主题。
- Do 区分内容、提示和操作层级，保留来源文字的换行与长链接折行。
- Do 保留主要控件的 44px 高度、可见键盘焦点及减少动态效果支持。
- Do 将空、加载、失败、禁用与选中状态写清楚，错误提供恢复操作。
- Do 使用真实照片；文档预览中的几何占位图必须标明“布局示例”。

### Don't:
- Don't 绕过 App 的蓝色状态配置，重新引入组件库默认绿色交互态。
- Don't 把根字号当作实际正文字号，或把所有说明文字统一描述成同一字号。
- Don't 添加装饰性渐变、营销文案或虚构照片库内容。
- Don't 将主要触控目标的尺寸要求误写为所有小按钮均已满足。
- Don't 将等高排列与瀑布流的完整图像展示规则套用到允许裁切的方形布局。
