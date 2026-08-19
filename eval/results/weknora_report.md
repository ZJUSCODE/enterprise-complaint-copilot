# Copilot Agent Evaluation Report

- Evaluation mode: `runtime_rag`
- Total cases: **92**
- RAG status: `ready`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 0.9333 |
| `tool_selection_accuracy` | 0.9 |
| `citation_hit_rate` | 0.0 |
| `rag_case_success_rate` | 0.1509 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 4731.12 |
| `latency_p95_ms` | 9185.7 |
| `retry_success_rate` | 1.0 |

## Case Counts

| Suite | Cases |
| --- | ---: |
| `rag_cases` | 53 |
| `route_cases` | 15 |
| `tool_cases` | 10 |
| `guardrail_cases` | 12 |
| `memory_cases` | 2 |

## Failed Cases

- `rag` 普通退货还在 7 天无理由范围内，应该先查什么？ | expected `POL-001` | actual `['782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', 'ff25bc5f-6987-4ff2-bb9f-d1fa49ece5d7', '47cb3454-3596-43d4-ae76-5fcd590c0653']`
- `rag` 用户签收 3 天内想退货，没有质量问题，客服应该按什么基线处理？ | expected `POL-001` | actual `['7dbe54b9-7947-4126-bcd0-99e72cae6abb', '782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', '6fd38803-3fcd-45b7-8abb-3f2fbc02ca93']`
- `rag` 一线客服能不能对高风险用户口头承诺超额赔付？需要保留什么依据？ | expected `POL-005` | actual `['fc325e5c-68a6-4d9f-922b-9b81952a039f', 'f648e28e-8a6e-4315-acc3-e4db0418924e', 'a260e91c-0104-4c4b-ac09-d590f45b6505']`
- `rag` 物延误超过 7 天并且包装破损，客服应该怎么安抚？ | expected `POL-002` | actual `['68745b1c-cf96-45a0-96ae-fd8d5ccdd535', '42ffa59d-7059-475d-ad55-a1559153421b', '2e3bc5da-cd73-4e50-b3f5-f3f406479322']`
- `rag` 包裹晚到且外包装损坏，应该先补发还是先取证？ | expected `POL-002` | actual `['42ffa59d-7059-475d-ad55-a1559153421b', '931d9a9f-1234-468d-9341-a77faafd631a', '68745b1c-cf96-45a0-96ae-fd8d5ccdd535']`
- `rag` 高价值商品物流延误，客服能不能扩大赔付金额？ | expected `POL-002` | actual `['f5cef149-5593-4736-a4ac-a5ad1c2576bf', '68745b1c-cf96-45a0-96ae-fd8d5ccdd535', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb']`
- `rag` 3C 数码拆封后出现质量问题，应该怎么处理？ | expected `POL-003` | actual `['a20ffb86-5897-4564-94c1-dd59221b3eff', 'c4315217-5126-485e-a128-79739540d8b6', '3b82ee61-ac97-4137-b09a-470fe518482e']`
- `rag` 手机已拆封，用户说功能异常，客服应该收集哪些证据？ | expected `POL-003` | actual `['c4315217-5126-485e-a128-79739540d8b6', '41849de9-ba97-4020-85f2-7b03f4759319', 'a20ffb86-5897-4564-94c1-dd59221b3eff']`
- `rag` 耳机拆封后用户主观不满意，能不能直接套用无理由退货？ | expected `POL-003` | actual `['a20ffb86-5897-4564-94c1-dd59221b3eff', '782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', 'fbabf48a-e35a-4a49-af39-3749349663aa']`
- `rag` 生鲜坏了并且冷链超时，运费和货款怎么赔？ | expected `POL-004` | actual `['de5f6889-f1e1-4dcc-8255-5f9a51a2b3e1', '191ed885-cbb2-4d7b-9c63-6e2731c645cf', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb']`
- `rag` 水果签收后发现腐烂，用户提供照片时应该走补发还是退款？ | expected `POL-004` | actual `['d88599a8-dba4-4113-aa41-e61da8f407a6', 'edf68902-5a9b-4e6d-9d4f-459f6c2d3516', 'dd29cc50-2fd6-4fc6-9b03-a5134bddb9fe']`
- `rag` 生鲜重复索赔账户又说冷链超时，应该直接赔付吗？ | expected `POL-004` | actual `['de5f6889-f1e1-4dcc-8255-5f9a51a2b3e1', '783b7c3e-9dbf-4697-8c35-452143c0aa95', 'd5096aa7-a557-4856-9d46-be0f473329e8']`
- `rag` 高风险用户要求超额赔付，客服能不能直接承诺？ | expected `POL-005` | actual `['fc325e5c-68a6-4d9f-922b-9b81952a039f', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb', 'a260e91c-0104-4c4b-ac09-d590f45b6505']`
- `rag` 风险分很高的账户多次重复索赔，应该保留什么记录并走谁复核？ | expected `POL-005` | actual `['fc325e5c-68a6-4d9f-922b-9b81952a039f', '800575bd-12b0-4363-91d3-bfae5eca998a', 'a260e91c-0104-4c4b-ac09-d590f45b6505']`
- `rag` 主管复核前，客服可以先给高风险账户全额赔付承诺吗？ | expected `POL-005` | actual `['fc325e5c-68a6-4d9f-922b-9b81952a039f', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb', '5595328d-6bc2-4b9c-b548-1332fe718382']`
- `rag` 定制刻字的商品签收后想退，能按 7 天无理由处理吗？ | expected `POL-010` | actual `['782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', 'ff25bc5f-6987-4ff2-bb9f-d1fa49ece5d7', '6fd38803-3fcd-45b7-8abb-3f2fbc02ca93']`
- `rag` 鲜活易腐的生鲜类商品支持无理由退货吗？ | expected `POL-010` | actual `['d88599a8-dba4-4113-aa41-e61da8f407a6', '390be7d9-82df-4414-8da7-9d625a99ffae', '383ca697-6948-43aa-887f-09d4f84af72c']`
- `rag` 用户上传了开箱视频证明商品质量问题，单笔 300 元可以先行赔付吗？ | expected `POL-011` | actual `['00175095-3d11-4460-a7cc-74bea1838fef', '900f170b-2801-4bd2-b1e2-9f3888e185e8', '5e74f804-c2d3-4517-96a7-e1749e36162a']`
- `rag` 手机 10 天内出现性能故障，按三包应该怎么处理？ | expected `POL-012` | actual `['c4315217-5126-485e-a128-79739540d8b6', '3b82ee61-ac97-4137-b09a-470fe518482e', '13348a53-b09e-4826-aca5-01af47059392']`
- `rag` 一箱水果 70% 烂了，按生鲜赔付分级应该怎么处理？ | expected `POL-013` | actual `['e8acd383-c4ac-4bb0-a416-a8e5935f6d1f', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb', 'de5f6889-f1e1-4dcc-8255-5f9a51a2b3e1']`
- `rag` 冷链包裹签收时已经化冻，责任怎么判定？ | expected `POL-014` | actual `['d88599a8-dba4-4113-aa41-e61da8f407a6', 'de5f6889-f1e1-4dcc-8255-5f9a51a2b3e1', 'd5096aa7-a557-4856-9d46-be0f473329e8']`
- `rag` 衣服吊牌剪了还能无理由退货吗？ | expected `POL-015` | actual `['782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', '58f84078-6869-4a23-8b9b-5042ae8852ae', '3ff1ecfe-aae4-4c44-8f69-a659d94fca5a']`
- `rag` 大件家具签收后发现断裂，应该怎么处理？ | expected `POL-016` | actual `['cccd55c1-6d9d-4b1d-8249-c457dd909a98', '8f5241e2-e2f1-48c9-8250-f2294309bdc6', 'efab4435-2685-4e8e-9d2f-2117c99d5204']`
- `rag` 美妆产品开封后过敏，什么条件下可以退？ | expected `POL-017` | actual `['390be7d9-82df-4414-8da7-9d625a99ffae', '5a42149c-f8b6-4a9d-9a54-53f122c41692', 'e2de52b6-efb9-49a1-8a4d-5e4a40fe2304']`
- `rag` 食品里发现异物，应该按什么流程处理？ | expected `POL-018` | actual `['f60642ee-4c5c-4015-8f46-ca668e8e5260', 'aebc11ae-26a3-4dda-89a7-e9b810fd638d', '30a3ca77-cae4-4dc9-a8e5-9035994242b2']`
- `rag` 退款提交后一般多久到账？ | expected `POL-019` | actual `['2e8547a7-6e54-4a22-b094-3e59e5dfcd77', '47cb3454-3596-43d4-ae76-5fcd590c0653', '03a1e338-0bc8-4fb9-b537-4849ade842cd']`
- `rag` 无理由退货的运费应该谁承担？ | expected `POL-020` | actual `['47cb3454-3596-43d4-ae76-5fcd590c0653', 'ff25bc5f-6987-4ff2-bb9f-d1fa49ece5d7', '782a1e39-d8a3-4c00-a1a4-0a530e78f9f2']`
- `rag` 快递确认丢件了，客服应该怎么处理？ | expected `POL-021` | actual `['edf68902-5a9b-4e6d-9d4f-459f6c2d3516', '782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', '42ffa59d-7059-475d-ad55-a1559153421b']`
- `rag` 买完 3 天降价了能申请补差价吗？ | expected `POL-022` | actual `['782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', '40433a3f-0949-4cdd-b11a-2880af299cf1', '2e8547a7-6e54-4a22-b094-3e59e5dfcd77']`
- `rag` 用户要求删除全部个人信息，应该走什么流程？ | expected `POL-024` | actual `['ca638322-e88c-452b-a78c-5fcdb84dbe9f', '51637503-b07f-4a69-94bc-09898410c328', 'f79181d2-4137-4330-b871-404129f3bd09']`
- `rag` 用户说要投诉到 12315，一线客服应该怎么办？ | expected `POL-025` | actual `['2e8547a7-6e54-4a22-b094-3e59e5dfcd77', '6c6154be-9442-4b2b-ba72-7163448b64ca', '6f777588-e6fd-4a06-8877-fc32e3ebcd03']`
- `rag` 付费会员退货免运费权益和品类政策冲突时怎么处理？ | expected `POL-026` | actual `['1c07dedc-c908-4925-8ce3-a173d4e3fdb2', '782a1e39-d8a3-4c00-a1a4-0a530e78f9f2', '1807e4ae-939e-40c8-a439-96663ba86b66']`
- `rag` 跨境保税仓商品非质量问题支持无理由退货吗？ | expected `POL-027` | actual `['cebc72b5-225c-49bb-ae8d-6c8c950fab22', '1c07dedc-c908-4925-8ce3-a173d4e3fdb2', '2ff803b8-92ab-4721-8a4c-f0f3427e5900']`
- `rag` 收到的商品与页面材质描述不符，怎么处理？ | expected `POL-028` | actual `['b6133288-1a67-4ae4-b05b-7bfcdd7829ab', '11ee7339-eeff-4247-89b7-691cd3d1eceb', 'ff25bc5f-6987-4ff2-bb9f-d1fa49ece5d7']`
- `rag` 工单结案后多久需要回访？ | expected `POL-030` | actual `['bc734770-8f0a-47d6-a437-2254faa7cd86', 'f5cef149-5593-4736-a4ac-a5ad1c2576bf', '10cdffdf-35d3-42d2-b2dc-29b50120ddc2']`
- `rag` 用户反馈账号被盗刷下单，第一优先动作是什么？ | expected `POL-031` | actual `['25cfb0ed-435f-47bc-951c-db9b2991c268', 'a215a6ac-c405-4c85-8705-befcda1df34f', 'bc734770-8f0a-47d6-a437-2254faa7cd86']`
- `rag` 客服可以对用户说『你爱投诉就投诉』吗？ | expected `POL-032` | actual `['8734a66e-5e12-4335-9c7a-36cd2b4ebbee', '2e8547a7-6e54-4a22-b094-3e59e5dfcd77', 'b5c8fcaa-3be9-4f84-be53-a08a7506c8c2']`
- `rag` 虚拟商品激活码发错了怎么处理？ | expected `POL-040` | actual `['7ccb417a-3d5b-4d2d-a950-9a0552aa50aa', 'e733c77d-fc15-4267-881a-fef2fdd464c9', 'd0725884-4eef-4beb-be8f-45466be8ce17']`
- `rag` 儿童玩具缺少 3C 认证标识应该怎么处理？ | expected `POL-042` | actual `['1b83ce5c-2e96-47a4-8f49-0232c3f8a0f4', '6caad7b3-91c6-4ba2-8cfa-367f8fd1d449', '00175095-3d11-4460-a7cc-74bea1838fef']`
- `rag` 活体宠物签收 48 小时内死亡，需要什么凭证？ | expected `POL-043` | actual `['1b83ce5c-2e96-47a4-8f49-0232c3f8a0f4', 'f5639a72-68f5-46a8-83ef-fe22fa657d6f', 'fc0d1f05-6227-44a2-b172-83dcec5252a5']`
- `rag` 单笔现金赔偿超过 1000 元需要谁审批？ | expected `POL-047` | actual `['a9849cb3-2647-4d37-9efa-18076d7741c4', 'f602bb6d-c8e9-4ef0-bbf5-aa143ae768eb', 'd6a3c11c-7c31-48a1-85cd-297c6dbc9dfb']`
- `rag` 二手手机成色描述与实物不符怎么处理？ | expected `POL-048` | actual `['792741d1-f004-4e70-8166-400fcdcac422', 'b6133288-1a67-4ae4-b05b-7bfcdd7829ab', '00175095-3d11-4460-a7cc-74bea1838fef']`
- `rag` 家电延保服务覆盖哪些范围？ | expected `POL-049` | actual `['792741d1-f004-4e70-8166-400fcdcac422', '6321640b-6fc1-47eb-b796-86f57bae8f88', 'ecb80c30-b323-4449-8d64-4e8aeeb60037']`
- `rag` 大促期间物流延误几天才开始判定异常？ | expected `POL-002` | actual `['dc488788-e882-4fa3-acf5-ae401b24f0ee', '42ffa59d-7059-475d-ad55-a1559153421b', '68745b1c-cf96-45a0-96ae-fd8d5ccdd535']`
- `rag` 大促超卖导致订单被取消，补偿标准是什么？ | expected `POL-001` | actual `['d181a39b-399a-40a5-8b39-017c3a1feff8', 'dc488788-e882-4fa3-acf5-ae401b24f0ee', 'bbe24382-29ef-4099-af47-ffe43958e085']`
- `route` 最近的售后情况怎么样？有什么需要注意的？ | expected `langchain_rag` | actual `function_call_agent`
- `tool` 3C数码超过500元的退款需要哪些SOP依据？ | expected `search_policy_docs` | actual `query_refund_cases`

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
