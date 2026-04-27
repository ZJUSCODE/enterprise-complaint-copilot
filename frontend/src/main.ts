import { createApp } from 'vue';
import { createPinia } from 'pinia';
import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElForm,
  ElFormItem,
  ElInput,
  ElLoading,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSkeleton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTimeline,
  ElTimelineItem,
} from 'element-plus';
import 'element-plus/theme-chalk/base.css';
import 'element-plus/theme-chalk/el-alert.css';
import 'element-plus/theme-chalk/el-button.css';
import 'element-plus/theme-chalk/el-collapse.css';
import 'element-plus/theme-chalk/el-collapse-item.css';
import 'element-plus/theme-chalk/el-form.css';
import 'element-plus/theme-chalk/el-form-item.css';
import 'element-plus/theme-chalk/el-input.css';
import 'element-plus/theme-chalk/el-loading.css';
import 'element-plus/theme-chalk/el-message.css';
import 'element-plus/theme-chalk/el-message-box.css';
import 'element-plus/theme-chalk/el-option.css';
import 'element-plus/theme-chalk/el-popper.css';
import 'element-plus/theme-chalk/el-progress.css';
import 'element-plus/theme-chalk/el-radio-button.css';
import 'element-plus/theme-chalk/el-radio-group.css';
import 'element-plus/theme-chalk/el-select.css';
import 'element-plus/theme-chalk/el-skeleton.css';
import 'element-plus/theme-chalk/el-table.css';
import 'element-plus/theme-chalk/el-table-column.css';
import 'element-plus/theme-chalk/el-tag.css';
import 'element-plus/theme-chalk/el-timeline.css';
import 'element-plus/theme-chalk/el-timeline-item.css';
import App from './App.vue';
import router from './router';
import './assets/styles.css';

const app = createApp(App);

app.use(createPinia());
app.use(router);
[
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSkeleton,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTimeline,
  ElTimelineItem,
].forEach((component) => {
  app.component(component.name!, component);
});
app.use(ElLoading);

app.mount('#app');
