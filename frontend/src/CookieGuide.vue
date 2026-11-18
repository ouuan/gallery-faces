<script setup lang="ts">
import { ref } from "vue";
import { NButton, NModal } from "naive-ui";
import { X } from "@lucide/vue";

const show = ref(false);
</script>

<template>
  <button class="text-button" aria-haspopup="dialog" @click="show = true">
    Cookie 导出指南
  </button>
  <n-modal v-model:show="show">
    <div
      class="form-dialog cookie-guide"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cookie-guide-title"
    >
      <header class="guide-header">
        <h2 id="cookie-guide-title">Cookie 导出指南</h2>
        <n-button quaternary aria-label="关闭导出指南" @click="show = false">
          <template #icon><X :size="20" /></template>
        </n-button>
      </header>
      <div class="guide-content">
        <p class="muted guide-intro">
          在已登录平台的浏览器中导出文件，再上传到这里。浏览器可以与图库运行在不同设备上。
        </p>
        <ol class="guide-steps">
          <li>
            <h3>登录要导入的平台</h3>
            <p>
              打开
              <a href="https://www.instagram.com/" target="_blank" rel="noopener noreferrer">Instagram</a>
              或
              <a href="https://x.com/" target="_blank" rel="noopener noreferrer">X</a>，
              登录账号并完成验证。仅支持公开账号的公开帖子；锁推、私密或无法确认公开状态的内容会被拒绝。
            </p>
          </li>
          <li>
            <h3>导出当前网站的 Cookies</h3>
            <p>任选以下一种方式导出</p>
            <p>
              <strong>Chrome / Edge：</strong>安装
              <a
                href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
                target="_blank"
                rel="noopener noreferrer"
              >Get cookies.txt LOCALLY</a>。
              在平台页面打开扩展，选择 Netscape 格式，导出当前网站。
            </p>
            <p>
              <strong>Firefox：</strong>安装
              <a
                href="https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/"
                target="_blank"
                rel="noopener noreferrer"
              >Export Cookies</a>。
              在平台页面打开扩展，选择当前域名（current domain），保存文件。
            </p>
            <p>
              <strong>gallery-dl 命令：</strong>在安装了浏览器的电脑上
              <a
                href="https://github.com/mikf/gallery-dl#installation"
                target="_blank"
                rel="noopener noreferrer"
              >安装 gallery-dl</a>，然后在终端运行对应平台的命令。以下以 Firefox 为例：
            </p>
            <p>Instagram：</p>
            <pre class="guide-command"><code>gallery-dl --ignore-config --cookies-from-browser firefox/.instagram.com --cookies-export instagram-cookies.txt</code></pre>
            <p>X / Twitter：</p>
            <pre class="guide-command"><code>gallery-dl --ignore-config --cookies-from-browser firefox/.x.com --cookies-export x-cookies.txt</code></pre>
            <p>
              命令会在当前目录生成对应的 Netscape .txt 文件，无需添加帖子链接。
              使用 Chrome 或 Edge 时，将 <code>firefox</code> 换成 <code>chrome</code>
              或 <code>edge</code>，保留后面的域名，以便只导出目标平台。
              如需指定浏览器配置文件，可写成 <code>chrome/.x.com:Default</code>，
              将 <code>Default</code> 换成已登录账号所在的配置文件名或路径。
            </p>
            <p class="muted">
              若提示数据库被占用，关闭浏览器后重试；若无法解密 Cookie，可改用上面的扩展导出。
              更多参数见
              <a
                href="https://gdl-org.github.io/docs/options.html#cookie-options"
                target="_blank"
                rel="noopener noreferrer"
              >gallery-dl Cookie 选项说明</a>。
            </p>
            <p class="muted">
              仅导出目标平台，不要选择所有网站。文件应为 Netscape 格式的 .txt，
              不超过 1 MiB；JSON 或复制的 Cookie 请求头无法直接上传。
            </p>
          </li>
          <li>
            <h3>上传到对应平台</h3>
            <p>
              关闭此指南，在 Instagram 或 X / Twitter 一栏点击「上传 / 替换」。
              两个平台分别导出、分别上传，替换后用于后续下载任务。
            </p>
            <p class="muted">
              「已配置」仅表示文件已保存。可导入一个图片帖子验证；若登录失效，
              请在浏览器重新登录并导出，再替换文件、重试失败任务。
            </p>
          </li>
        </ol>
        <p class="guide-privacy">
          Cookie 包含登录凭据，请像密码一样保管，只上传到自己信任的图库，勿分享或提交到代码仓库
        </p>
      </div>
      <footer class="guide-footer">
        <n-button @click="show = false">关闭指南</n-button>
      </footer>
    </div>
  </n-modal>
</template>

<style scoped>
.cookie-guide {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}
.guide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px 12px 24px;
}
.guide-header h2 {
  margin: 0;
}
.guide-content {
  min-height: 0;
  overflow-y: auto;
  overflow-wrap: anywhere;
  padding: 0 24px;
}
.guide-intro {
  margin-top: 0;
}
.guide-steps {
  padding-left: 24px;
  margin: 20px 0;
}
.guide-steps li + li {
  margin-top: 24px;
}
.guide-steps h3 {
  margin: 0 0 8px;
}
.guide-steps p {
  margin: 8px 0 0;
}
.guide-content a {
  text-decoration: underline;
  text-underline-offset: 3px;
}
.guide-command {
  margin: 8px 0 0;
  padding: 12px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.guide-privacy {
  border-top: 1px solid var(--line);
  padding-top: 16px;
  margin: 0 0 16px;
}
.guide-footer {
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--line);
  padding: 12px 24px;
}
</style>
