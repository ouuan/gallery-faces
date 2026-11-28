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
    { path: '/heatmap', component: () => import('./Heatmap.vue') },
    { path: '/face-game', component: () => import('./GameRoom.vue'), props: { solo: true, key: 'face-solo' } },
    { path: '/face-game/play/:code', component: () => import('./GameRoom.vue'), props: { solo: true, key: 'face-play' } },
    { path: '/face-game/rooms/:code?', component: () => import('./GameRoom.vue') },
    { path: '/history-quiz', component: () => import('./GameRoom.vue'), props: { solo: true, history: true, key: 'history-solo' } },
    { path: '/history-quiz/play/:code', component: () => import('./GameRoom.vue'), props: { solo: true, history: true, key: 'history-play' } },
    { path: '/history-quiz/rooms/:code?', component: () => import('./GameRoom.vue'), props: { history: true, key: 'history-room' } },
    { path: "/admin/:section?", component: Admin },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior(to, from, saved) {
    if (to.path === from.path || (to.matched[0] && to.matched[0] === from.matched[0])) return;
    return saved || { top: 0 };
  },
});
createApp(App).use(createPinia()).use(router).mount("#app");
