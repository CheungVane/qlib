// Keep module-loading failures visible even when app event handlers never start.
import('./app.js').catch(() => {
  const content = document.getElementById('content');
  content.replaceChildren();
  const message = document.createElement('p');
  message.textContent = '界面资源加载失败。服务可能仍运行旧版本，请重启工作台服务后刷新页面。';
  const retry = document.createElement('button');
  retry.textContent = '重新加载';
  retry.onclick = () => location.reload();
  content.append(message, retry);
});
