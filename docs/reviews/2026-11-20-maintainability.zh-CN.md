# Sub2 代码维护审查 · 2026-11-20

最先要修两件事。第一，用户改选字幕后，较早发出的下载请求有机会把旧选择重新盖回来。第二，开发者启动本地版本时，启动器可能关闭占用同一端口的其他程序。前者在模拟下载中复现；后者已核对代码，没有在真实桌面上尝试。全部维护事项由 [#175](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/175) 跟踪。

审查基准是 [main 的 e423785](https://github.com/PeterShanxin/Meowcal-Sub-2/commit/e423785e6653f91341cbf951e1cd875786558ea1)。从选片和下载跟到字幕上屏，检查了 React 工作室、Python 后台、Windows 启动器与桌面外壳、翻译进程的归属，以及仓库运行测试时用的质量规则。以下 11 项发现来自这次检查；没有逐行审计所有平台依赖。文中的“次数”是对模拟输入实际计数，不能折算成观看时卡顿了多少秒。

## 哪些代码可以直接共用

| 功能 | 可以沿用的代码 | 真正缺少的部分 |
| --- | --- | --- |
| **译文跟播** | 已有匹配器给出字幕编号和开始时间，播放时钟判断暂停和跳转，字幕显示器决定何时换行或清空。 | 只有译文时，现在取回匹配文字就结束。要保留是哪一句、何时在屏幕出现，以及能否确定是同一句。位置确认后直接用译文文件的时间，继续走双轨跟播的显示流程。见 [#164](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/164)。 |
| **原文补译** | 已有实时翻译、带上下文的补译、播放时钟和译文显示器。先看当前对白和后台翻译可使用同一套翻译能力。 | 为整份字幕跟踪完成情况，眼前的一句优先。译完后在当前播放位置接入，正在暂停就继续停在那里。现有补空缺一次最多尝试 120 行，不能据此认定整部片已译完。见 [#165](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/165)。 |

两种路径的讨论名称、观看流程和交接时序见[字幕路径图](../subtitle-fallback-design.md)。下面的维护事项可独立处理，修复可按影响分批进行。

## 优先修复：可能覆盖选择或影响其他程序

### 1. 较早的准备请求可以覆盖较新的选择 · [#166](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/166)

在同一片名下，先请求准备两份字幕，暂缓第一次下载；随后选择屏幕直译并等待就绪；最后让第一次下载完成。后台最后保存的会话变回了第一次选的双文件会话。几个准备入口都要等待下载，然后各自写回状态。自动选择入口在写回前检查片名，相同片名下的两次选择仍无法区分。相对地，开始播放已经会在等待之后核对会话身份。见 [controller.py 第 1212 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1212)、[controller.py 第 1399 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1399) 和 [controller.py 第 1557 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1557)。

**修好怎么算：** 给每一次准备绑定当时的搜索和选择。旧请求即使最后才成功或失败，也不能改动新会话、进度、提示或后台补译。用同一片名连选两次，以及下载途中改搜另一部片来验收。

### 2. 开发启动器按端口和程序名关进程 · [#170](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/170)

启动器会查找监听 8765 端口的进程并强制关闭，还会按名字关闭桌面外壳、按命令行匹配 Python 后台。端口只能说明程序占用了这个位置，无法证明它属于当前项目副本。开发者已经打开的安装版也在匹配范围内。桌面外壳有记录自身后台进程的做法可供复用。见 [run_app.vbs 第 117 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/run_app.vbs#L117) 和 [backend_process.rs 第 114 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src-tauri/src/backend_process.rs#L114)。

**修好怎么算：** 只停止能确认由当前副本启动的进程；遇到其他程序占用端口时提示冲突。用模拟的已安装版本、无关程序和自定义端口验证，避免在开发者电脑上试关真实程序。

## 容易出现选错文件、重复下载或残留工作的地方

### 3. 手动配对缺少文件与片名的归属检查 · [#166](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/166)

用现有测试里的两个合法文件 ID，给准备请求传另一个片名 ID，后台接受了请求，并给会话写上了这个片名。模拟验证的是后台接口；正常界面的列表会过滤文件。仅译文入口已经检查文件属于所选片名，手动配对入口可复用这个判断。见 [controller.py 第 1080 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1080) 和 [controller.py 第 1451 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1451)。

**修好怎么算：** 在消耗下载额度前核对两份文件。省略片名时仍能由文件推断；来源后来补全了同一片名的信息时，也能保留合法选择。

### 4. 一种双语字幕选择在界面里有两种解释 · [#167](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/167)

用户选择“原文字幕自带的译文”时，后台把这个选择保存为 `__source__`。界面在片名被重新归类后检查是否要重新准备，却把所有双下划线开头的译文选项都当作空值。用真实的 TypeScript 比较函数试过，两份选择完全相同、只有片名标识更新，结果仍然是“需要重新准备”。见 [controller.py 第 1183 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1183) 和 [mappers.ts 第 157 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/ui/src/state/mappers.ts#L157)。

**修好怎么算：** 生成准备请求、比较准备结果时，对“字幕自带译文”使用同一个含义。给现有的重新归类测试补上双语文件、真正换文件和仅屏幕直译三组用例。

### 5. 同一份原文字幕可以同时下载两次 · [#168](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/168)

选择原文、进入译文标签页都可能发起检查。界面可以复用查完的结果，却没有复用正在等待的那一次请求。后台对已下载的路径也只在下载完成后登记。并发检查同一个模拟文件两次，实际调用了两次来源下载接口。见 [app.tsx 第 445 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/ui/src/app.tsx#L445) 和 [controller.py 第 1039 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1039)。

**修好怎么算：** 同一批搜索结果里的同一文件只发起一次下载，检查和准备可以等待同一个结果。失败后可以重试；换了片名后，旧下载晚到也不能占用新选择的位置。

### 6. 搜索被取消后，字幕来源的查询还在运行 · [#173](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/173)

搜索会同时询问多个来源，以便先显示先返回的结果。模拟来源正在等待时，取消并等待总搜索结束，来源查询仍然在等；释放它后才结束。每个来源已有自己的超时，但失去用途后仍占用一次请求。见 [aggregator.py 第 204 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/subtitle_sources/aggregator.py#L204)。

**修好怎么算：** 由发起搜索的一方负责取消并收回未完成的工作。普通的单一来源失败仍能显示其他结果。覆盖用户取消和发布中间结果失败两种退出方式。

### 7. 一个窗口更新得慢，字幕条也可能跟着等 · [#174](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/174)

后台按窗口顺序逐个发送更新，等待一次发送时没有单独的截止时间。显示下一条字幕也要等待这条发送路径。另一个问题在首次连接：窗口先加入名单，再发送初始状态和样式，这两次发送都发生在清理代码生效之前。此项来自代码阅读，没有测到桌面实际延迟。见 [server.py 第 342 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/server.py#L342) 和 [controller.py 第 1701 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/overlay/controller.py#L1701)。

**修好怎么算：** 慢窗口有等待上限，正常字幕条能按顺序收到“显示、清空、再显示”。初始发送失败的窗口能从名单移除。检查停止、重新连接和是否有积压发送任务。

## 播放和翻译中的重复计算

### 8. 找下一次换字幕的时间，会从片头开始查 · [#169](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/169)

构造了 1,000 条不重叠的译文字幕。播放到最后一句时，显示器先检查了全部 1,000 条；找这句何时结束，又检查了已按时间排序的 2,000 个起止点。目标轨在准备时就已经掌握这些时间。见 [presentation.py 第 90 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/presentation.py#L90) 和 [presentation.py 第 114 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/presentation.py#L114)。

**修好怎么算：** 在已排序的时间点里直接找到下一个位置。对当前可见的字幕，比较按区间查询和顺序播放游标的效果。两人同时说话、长句包着短句、向后拖动和无字幕时段都要维持原表现；分别记录长短字幕文件的耗时与检查次数。

### 9. 每挑一行补译，都要把整份文件再问一遍 · [#169](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/169)

用 1,000 行原文，其中 120 行需要补译。挑出这 120 行时，实际查询“这行已有译文吗” **120,000 次**。这还没算模型翻译和寻找上下文的工作。播放中要跟随用户跳转确实需要调整优先顺序，但待译列表没有必要每次从头重建。见 [gapfill.py 第 70 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src/meocosub2/gapfill.py#L70)。

**修好怎么算：** 保留这一轮待译的位置，选中某行后再检查一次是否已被实时翻译填上。跳转、候选文件切换、已有译文更新和尾部回到片头均需覆盖。先用同一份样本报告减少了多少查询，再测整段翻译耗时。

## 开发者可能被验证结果误导的地方

### 10. 普通启动可能运行旧的选区界面 · [#170](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/170)

桌面外壳把选区窗口等资源打包进程序。开发启动器自行维护一张“何时重新编译”的文件清单，它查看仓库顶层的 Cargo.lock；实际文件在 src-tauri/Cargo.lock。选区和启动画面的资源也没有进入这张清单。改动这些文件后，开发者可能看到上一次编译出来的界面。见 [run_app.vbs 第 153 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/run_app.vbs#L153) 和 [tauri.conf.json 第 7 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/src-tauri/tauri.conf.json#L7)。

**修好怎么算：** 尽量使用构建工具本身掌握的依赖关系。只改真实的锁文件、只改选区资源时都应生效；什么都没改时仍可快速启动。

### 11. 从覆盖率名单移除模块，可以让原来失败的检查变绿 · [#171](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/171)

覆盖率表示测试运行时执行了多少代码。用两个等大的模拟模块，一个覆盖 100%，另一个 0%，门槛设为 79%，结果按预期失败。只从配置里的统计名单移除后者，测试内容完全没变，检查却通过。因为“实际统计谁”和“应该统计谁”都由修改后的同一张名单决定。现有测试能发现名单上有文件没被测到，无法发现有人改短名单本身。见 [check_maintainability.py 第 204 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/scripts/check_maintainability.py#L204) 和 [test_maintainability.py 第 113 行](https://github.com/PeterShanxin/Meowcal-Sub-2/blob/e423785e6653f91341cbf951e1cd875786558ea1/tests/test_maintainability.py#L113)。

**修好怎么算：** 检查一次修改时，把统计范围与修改之前的版本比较。合法改名、删除旧模块或加入新模块都应有明确结果；仍在使用的模块无故消失应被指出。

## 验证范围和已有事项

在干净的主分支快照上运行了相关的 248 个现有测试，全部通过，另有 29 个子用例通过。另做了七项隔离的 Python 检查，分别验证旧准备覆盖新会话、片名归属、重复下载、两个遍历次数、缩减覆盖名单，以及取消搜索后仍有查询在运行。界面双语选项另用仓库里的 TypeScript 函数核对。启动器和窗口发送的发现来自源码。没有在这次检查中下载真实字幕、关闭用户程序、测量真实视频的字幕延迟或比较两个模型进程的速度。

已有问题沿用原工单：控制器测试依赖内部字段 [#49](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/49)、自动选字幕缺少对齐报告 [#48](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/48)、工作室界面已有的可访问性与状态更新问题 [#38](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/38)。大文件的行数用于定位需要细读的地方；本报告的修改建议都对应具体行为或计数。

## 修复结果

以上 11 项记录的是审查当时的表现。对应的 8 个维护问题按下面几组合并，有些问题出在同一段代码，所以由同一份改动解决。

| 发现 | 修复后怎样 | 怎样检查 |
| --- | --- | --- |
| 1、3、4、5 · 选择和下载 | 用户最后一次选择生效。双语字幕换组后仍保持选中，同时检查同一份字幕共用一次下载。 | 用等待时间不同的下载模拟快速改选、换片和失败重试，再跑工作室测试。[改动 #181](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/181) |
| 2、10 · 本机启动器 | 重开开发版时只处理当前项目副本启动的程序。改了打包进程序的选区页面或依赖清单，下一次启动会重新编译。 | 在这台 Windows 电脑上单独改两种文件，核对生成的程序发生变化；让另一程序占用自定义端口，确认它仍可连接。[改动 #180](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/180) |
| 6、7 · 搜索和窗口 | 取消搜索会收回仍在等待的查询。慢窗口不会挡住健康窗口；窗口重连能恢复当前字幕，也能恢复没有字幕的状态。 | 模拟来源取消、窗口堵塞和退出，再用浏览器核对重连后的字幕。[改动 #177](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/177) |
| 8、9 · 找字幕和挑待翻内容 | 按开始和结束时间找当前字幕，挑待翻内容时复用已查过的结果。 | 1,000 行里挑 120 行，检查次数由 120,000 次降至 1,120 次；另测同时出现的字幕、两句之间为空和倒退播放。[改动 #178](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/178) |
| 11 · 测试覆盖范围 | 一个还在使用的界面模块被改名或从测试清单移除，合并前的检查会指出来。 | 在临时仓库中分别模拟改名、真正删除和仅从清单移除。[改动 #179](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/179) |

两条缺失的观看路径也有了各自的验收记录。[Path 2 的匹配与跟播实测](../target-track-replay.md)比较了现在使用的「先翻译再找」和直接按跨语言含义找位置的结果。[Path 3 的本机翻译实测](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/182)记录了眼前一句等多久、整段何时补完，以及用了多少内存。
