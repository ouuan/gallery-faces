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
    { path: "/", component: Gallery, children: [
      { path: "posts/:key", name: "gallery-post", component: () => import("./PostDetail.vue"), props: route => ({ postKey: route.params.key }) },
    ] },
    { path: "/:mode(daily|random)", component: () => import("./PhotoDraw.vue"), props: true },
    { path: '/face-game', component: () => import('./FaceGame.vue') },
    { path: "/admin/:section?", component: Admin },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior(to, from, saved) {
    if (to.path === from.path || (to.matched[0] && to.matched[0] === from.matched[0])) return;
    return saved || { top: 0 };
  },
});
createApp(App).use(createPinia()).use(router).mount("#app");
