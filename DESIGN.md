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
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: -0.02em
  heading:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 19px
    fontWeight: 700
    lineHeight: 1.6
  section-label:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.6
  subheading:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 15px
    fontWeight: 700
    lineHeight: 1.6
  body:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  paragraph:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 550
    lineHeight: 1.6
  hint:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
  photo-caption:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.6
  photo-caption-mobile:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.6
  photo-title:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 14px
    fontWeight: 550
    lineHeight: 1.6
  photo-title-mobile:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
    fontSize: 13px
    fontWeight: 550
    lineHeight: 1.6
  button:
    fontFamily: v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"
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

<!-- impeccable:design-map -->
照片档案馆以真实照片及其来源为中心。蓝色只用于操作与选择；常驻容器靠表面色与细边框划分，浮层用遮罩与阴影。文字按标题、正文、提示和照片元信息分层。

主要控件高 44px，保留键盘焦点、减少动态效果及浅深主题。等高与瀑布流布局展示完整图像，方形布局可裁切。不要虚构照片库内容；预览占位图标明“布局示例”。

简单文案末尾不要逗号。

[基础色与布局](frontend/src/style.css)；[组件主题色](frontend/src/theme-colors.ts)（浅色与深色的占位文字、悬停和按下状态，由 [App](frontend/src/App.vue) 应用）。详见[完整设计指南](.impeccable/design-full.md)。
