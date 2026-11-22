import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import Gallery from "./Gallery.vue";
const Admin = () => import("./Admin.vue");
import "./style.css";
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Gallery },
    { path: "/daily", component: () => import("./DailyPhoto.vue") },
    { path: "/admin/:section?", component: Admin },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior(to, from, saved) {
    if (to.path === from.path) return;
    return saved || { top: 0 };
  },
});
createApp(App).use(createPinia()).use(router).mount("#app");
