# Render 弹窗要求绑卡怎么办

> 这是你在部署过程中可能遇到的唯一一个"卡住"的地方。按顺序做，不用花钱。

---

## 先搞清楚：这不是要你付钱

弹窗原文：

```
Add Card
Add credit card to verify your identity.
To verify your card, Render will perform a temporary authorization for $1 USD. You won't be charged.
```

翻译：**加卡是为了核验你的身份**。会做一笔 **1 美元预授权**（只是冻结额度做身份确认，**不是扣款**，不会入账）。

Render 官方文档 [render.com/docs/free](https://render.com/docs/free) 里，创建免费实例的完整流程是：
注册 → New → 选服务类型 → 选 Free → 完成。**其中没有任何付款步骤。**

官方 FAQ 甚至专门写了"没加付款方式"这种情况：

> If you **haven't** added a payment method and you would incur charges, Render instead disables your services for the duration of the current billing period.
> （如果**没有**添加付款方式又产生了费用，Render 会直接停掉你的服务，而不是扣钱。）

所以：**免费套餐 + 不填 LLM_API_KEY = 0 元**，这一条没有变。你遇到的弹窗是**风控身份核验**，不是套餐要求。

---

## 第 1 步：关掉代理，重新试（成功率最高的办法）

**触发这个弹窗最常见的原因就是代理/VPN**——Render 会看到你的访问来自机房 IP 或境外 IP，判定为可疑注册。

1. **关掉所有 VPN、加速器、科学上网工具**（包括系统代理和浏览器插件）
2. 确认方法：浏览器打开 `https://ip.sb`，看清楚显示的**国家/地区是不是中国**。如果是美国、日本、新加坡等，说明代理没关干净
3. 开一个**无痕窗口**（Ctrl+Shift+N）
4. 打开 https://render.com ，用 **GitHub 账号**登录
5. 右上角 **New +** → **Blueprint** → 选 `literature-agent` 仓库

**如果不再弹窗** → 继续：Branch 选 `main` → `CONTACT_EMAIL` 填你的邮箱 → `LLM_API_KEY` 留空 → 点 Apply。完成。

> 手机热点通常比家里的宽带更"干净"，如果家里网络还弹窗，可以用手机热点试一次。

---

## 第 2 步：还弹窗 → 发客服工单（复制下面的英文）

Render 后台右下角一般有个 **"?" / Help / Contact Support** 的入口，点进去选 **Submit a request**。
把下面的内容**整段复制粘贴**进去即可（我用英文写，客服处理更快；内容都是真实情况，没有编造）：

```
Subject: Cannot deploy a Free instance — signup is asking for a credit card to verify identity

Hello,

I am a student trying to deploy a Python (FastAPI) web service on the Free instance
type, for a university coursework project. My repository is public on GitHub:
https://github.com/SilentTensor/literature-agent

When I try to create the service, I get an "Add Card — Add credit card to verify your
identity" dialog. I would prefer not to add a payment method.

I understand from your documentation that a payment method is not required for Free
instances:

- https://render.com/docs/free — the "Create a Free instance" flow contains no
  payment step.
- https://render.com/docs/faq — "If you haven't added a payment method and you would
  incur charges, Render instead disables your services for the duration of the
  current billing period."

My service will stay strictly on the Free instance type, so there should be no charges.

Could you please either (a) review and clear the identity verification requirement on
my account, or (b) let me know what alternative verification I can provide?

Thank you very much for your help.

Best regards,
[把你的名字填在这里]
[把你的邮箱填在这里]
```

**注意事项：**
- 把最后两行方括号换成你自己的名字和邮箱（用你注册 Render 的邮箱）
- 如果仓库不是 `SilentTensor/literature-agent`，换成你自己的仓库地址
- 措辞要点：明确说"我只用免费套餐""我看到了官方文档说不需要付款方式"——这比单纯说"我不想绑卡"有效得多

---

## 第 3 步：客服也不给过 → 换方案

如果工单回复说必须绑卡，就别在这个平台上耗了。有两条路：

### 方案 X：香港轻量应用服务器（要花钱，但国内访问快很多）

- 腾讯云 / 阿里云的**香港**地域轻量应用服务器，**支付宝付款，不需要信用卡**
- 约 ¥100–300/年（学生认证还有优惠）
- **选香港而不是内地**：内地节点需要 ICP 备案，香港不需要，买了就能用
- 好处：国内访问延迟低（Render 美国节点平均 400ms 以上）；缺点：需要一点命令行操作，我可以一步步带你做

### 方案 Y：不折腾公网，就先在局域网用

- 你这台电脑已经在跑服务了，同一个 WiFi 下的人访问 `http://10.25.192.28:8765/` 就能用
- 缺点：对方必须和你连同一个 WiFi，而且你电脑不能关机
- 详见项目 `README.md` 里的"局域网分享"章节（含一条需要管理员权限执行的防火墙命令）

---

## 顺便说明：为什么不能用 Vercel / 腾讯云函数这类免卡平台

我核实过一圈，这些平台虽然免卡，但**技术上跑不了这个程序**，换了会白折腾：

| 平台 | 为什么不行 |
|---|---|
| Vercel | 单次请求最长 **300 秒**就被掐断；你这个调研任务要跑几分钟到十几分钟 |
| Netlify | 上限 **60 秒**，更短 |
| 腾讯云函数 / 阿里云函数计算 | 每次请求是**独立实例、内存不共享**。你的浏览器去查任务进度时，会查到"任务不存在" |
| Cloudflare Workers | 不支持 Python，且单请求 CPU 只有 10 毫秒 |

这个程序的架构是"后台跑一个长任务 + 浏览器不断轮询进度"，**必须有一个常驻进程**，所以只能用 Render 这类跑容器的平台。

---

## 附：关于绑卡的几个常见顾虑

**Q：绑了卡会不会莫名其妙被扣钱？**
只要服务类型选 **Free**、`LLM_API_KEY` **留空**，就不会产生任何费用。Render 免费套餐是按"实例小时"计费的，Free 类型价格为 0。

**Q：$1 预授权会真的扣走吗？**
不会。它是冻结不是扣款。但要提醒：部分国内银行对境外 $1 预授权会**占用额度**，释放可能要几天，提前有个心理准备。

**Q：不绑卡是不是更安全？**
某种意义上是的。按官方 FAQ，**没绑卡**的账号一旦产生费用，Render 是直接停服务；**绑了卡**的才会真扣钱。所以在你不确定会不会误操作的情况下，不绑卡反而更保险。

**Q：以后想升级付费怎么办？**
随时可以在控制台加卡，不影响现在。
