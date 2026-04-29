# SYDRRO TECH OS

本项目是一个本地运行的运营面板，用于资产调度、库存管理和订单状态查看。

## 本地运行

1. 将业务数据文件命名为 `data.xlsx`，放在本目录。
2. 双击 `start-local-server.bat`。
3. 浏览器会自动打开 `SYDRRO-TECH-V4.html`。

## GitHub Pages

开启 Pages 后可以访问：

`https://sydrro.github.io/techos/`

## 图片录单

本地服务模式下可在页面中使用“图片录单”，识别订单截图后补录机器、编号、租金和发货地，并写回 `data.xlsx`。

## 数据说明

`data.xlsx` 是订单数据源，`sydrro-backup.json` 是页面状态自动备份。公开仓库会展示这些数据，上传前请确认里面没有不希望公开的客户或订单信息。
