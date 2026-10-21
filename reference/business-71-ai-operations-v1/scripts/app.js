/* B71 AI Operations - static site controller.
 *
 * Every screen renders the prepared dataset in ./data/. Nothing here calls a
 * backend, a channel, an ERP or a remote computer. The remote-work screen is
 * deliberately empty until a real browser-control session exists, so the site
 * can never look connected when it is not.
 */
(function () {
  "use strict";

  var DATA = {
    dashboard: "dashboard.json",
    product: "product_listing.json",
    erp: "erp_items.json",
    orders: "order_fulfillment.json",
    remote: "remote_agent.json"
  };

  var state = {
    route: "dashboard",
    data: {},
    erpFilter: "all",
    productChannel: null,
    orderId: null
  };

  var view = document.getElementById("view");

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) { return; }
      if (key === "text") { node.textContent = String(value); return; }
      if (key === "html") { node.innerHTML = String(value); return; }
      if (key === "class") { node.className = String(value); return; }
      if (key.indexOf("on") === 0 && typeof value === "function") {
        node.addEventListener(key.slice(2), value);
        return;
      }
      node.setAttribute(key, String(value));
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) { return; }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function badge(text, kind) {
    return el("span", { class: "badge " + (kind || ""), text: text });
  }

  function statusBadge(code, label) {
    var kind = "info";
    if (code === "AUTO_OK" || code === "prepared" || code === "delivered" || code === "completed") { kind = "ok"; }
    else if (code === "REVIEW_REQUIRED" || code === "open" || code === "out_for_delivery") { kind = "warn"; }
    else if (code === "DUPLICATE" || code === "error") { kind = "err"; }
    return badge(label || code, kind);
  }

  function card(title, subtitle, body, top) {
    return el("article", { class: "card" }, [
      el("div", { class: "card-top" }, [el("h3", { text: title }), top || null]),
      subtitle ? el("p", { text: subtitle }) : null,
      body
    ]);
  }

  function section(title, note, body) {
    return el("section", { class: "section" }, [
      el("h2", {}, [title, note ? el("small", { text: note }) : null]),
      body
    ]);
  }

  function table(headers, rows, cellBuilders) {
    var head = el("thead", {}, [
      el("tr", {}, headers.map(function (h) {
        return el("th", { class: h.num ? "num" : null, text: h.label !== undefined ? h.label : h });
      }))
    ]);
    var body = el("tbody", {}, rows.map(function (row) {
      return el("tr", {}, headers.map(function (h, index) {
        var value = cellBuilders && cellBuilders[index] ? cellBuilders[index](row) : row[h.key];
        if (value && value.nodeType) { return el("td", { class: h.num ? "num" : null }, [value]); }
        return el("td", { class: h.num ? "num" : null, text: value === undefined || value === null ? "" : String(value) });
      }));
    }));
    return el("div", { class: "table-wrap" }, [el("table", {}, [head, body])]);
  }

  function download(filename, text, mime) {
    var blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: filename });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function toCsv(rows, columns) {
    function cell(value) {
      var text = value === undefined || value === null ? "" : String(value);
      if (/[",\n]/.test(text)) { return '"' + text.replace(/"/g, '""') + '"'; }
      return text;
    }
    var lines = [columns.map(function (c) { return cell(c.label !== undefined ? c.label : c.key); }).join(",")];
    rows.forEach(function (row) {
      lines.push(columns.map(function (c) { return cell(row[c.key]); }).join(","));
    });
    return lines.join("\n");
  }

  function pageHead(title, description) {
    return el("div", { class: "page-head" }, [
      el("div", {}, [el("h1", { text: title }), description ? el("p", { text: description }) : null]),
      el("div", { class: "toolbar" }, [
        el("button", {
          class: "btn",
          type: "button",
          text: "현재 화면 데이터 내려받기",
          onclick: function () {
            download(state.route + ".json", JSON.stringify(state.data[state.route], null, 2), "application/json;charset=utf-8");
          }
        })
      ])
    ]);
  }

  /* ---------------- dashboard ---------------- */

  function renderDashboard() {
    var data = state.data.dashboard;
    var cards = data.workflows.map(function (workflow) {
      return el("article", { class: "card workflow-card" }, [
        el("div", { class: "card-top" }, [
          el("h3", { text: workflow.title }),
          statusBadge(workflow.status_code, workflow.status_label)
        ]),
        el("p", { text: workflow.summary }),
        el("div", { class: "metrics" }, workflow.metrics.map(function (metric) {
          return el("div", { class: "metric" }, [
            el("span", { text: metric.label }),
            el("strong", { text: metric.value })
          ]);
        })),
        el("ul", {}, (workflow.notes || []).map(function (note) { return el("li", { text: note }); })),
        el("div", { class: "toolbar" }, [
          el("a", { class: "btn primary", href: workflow.href, text: "이 업무 열기" }),
          el("span", { class: "badge", text: workflow.issue })
        ])
      ]);
    });

    var runs = table(
      [
        { key: "workflow", label: "업무" },
        { key: "issue", label: "이슈" },
        { key: "result", label: "결과" },
        { key: "detail", label: "내용" },
        { key: "evidence", label: "증거" }
      ],
      data.recent_runs,
      [null, null, function (row) { return statusBadge(row.result_code, row.result); }, null, function (row) { return el("span", { class: "mono", text: row.evidence }); }]
    );

    return el("div", {}, [
      pageHead("B71 AI Operations", data.site.subtitle),
      el("div", { class: "notice warn", text: data.synthetic_notice }),
      section("업무 3종", null, el("div", { class: "grid cols-3" }, cards)),
      section("최근 실행 결과", "가상 샘플 실행 기록", runs),
      section("측정 기준", null, el("p", { class: "notice", text: data.measurement_note }))
    ]);
  }

  /* ---------------- product listing ---------------- */

  function renderProduct() {
    var data = state.data.product;
    var channels = data.channels;
    if (!state.productChannel || !channels.some(function (c) { return c.channel_id === state.productChannel; })) {
      state.productChannel = channels.length ? channels[0].channel_id : null;
    }
    var active = channels.filter(function (c) { return c.channel_id === state.productChannel; })[0];

    var channelPicker = el("div", { class: "toolbar" }, channels.map(function (channel) {
      return el("button", {
        class: "chip",
        type: "button",
        "aria-pressed": channel.channel_id === state.productChannel ? "true" : "false",
        text: channel.display_name,
        onclick: function () { state.productChannel = channel.channel_id; render(); }
      });
    }));

    var fieldRows = active ? active.fields.map(function (field) {
      return { label: field.label, key: field.key, value: field.value };
    }) : [];

    var issueRows = active ? active.issues.map(function (issue) {
      return {
        severity: issue.severity,
        code: issue.code,
        target: issue.target,
        message: issue.message
      };
    }) : [];

    var fieldTable = table(
      [
        { key: "label", label: "등록 항목" },
        { key: "key", label: "필드 키" },
        { key: "value", label: "입력 값" }
      ],
      fieldRows,
      [null, function (row) { return el("span", { class: "mono", text: row.key }); }, function (row) {
        return el("span", { class: row.value ? "" : "badge warn", text: row.value || "(값 없음)" });
      }]
    );

    var issueTable = issueRows.length ? table(
      [
        { key: "severity", label: "등급" },
        { key: "code", label: "코드" },
        { key: "target", label: "대상" },
        { key: "message", label: "내용" }
      ],
      issueRows,
      [function (row) { return statusBadge(row.severity === "error" ? "error" : "warn", row.severity === "error" ? "차단" : "주의"); }, null, null, null]
    ) : el("div", { class: "empty", text: "차단·주의 항목이 없습니다." });

    var preview = el("iframe", {
      class: "preview",
      title: "상품 상세 HTML 미리보기",
      sandbox: "",
      srcdoc: data.description_html
    });

    var manifestRows = (data.image_manifest.entries || []).map(function (entry) {
      return {
        role: entry.role,
        file_name: entry.file_name,
        size: entry.width_px + "x" + entry.height_px,
        byte_size: entry.byte_size,
        alt_text: entry.alt_text
      };
    });

    var plan = data.fill_plan || [];
    var planRows = [];
    plan.forEach(function (channelPlan) {
      (channelPlan.steps || []).forEach(function (step) {
        planRows.push({
          channel: channelPlan.display_name,
          order: step.order,
          action: step.action,
          target_label: step.target_label,
          classification: step.classification,
          requires_human: step.requires_human,
          rationale: step.rationale
        });
      });
    });

    return el("div", {}, [
      pageHead("상품등록", "공급 자료 → 표준 속성 → 판매채널별 등록 초안. 실제 판매채널 게시는 수행하지 않았습니다."),
      el("div", { class: "notice warn", text: data.synthetic_notice }),
      section("상품정보 목록", "합성 샘플 1건", el("div", { class: "split" }, [
        el("div", { class: "list" }, [
          el("div", { class: "list-item", "aria-current": "true" }, [
            el("strong", { text: "데모 USB-C 알루미늄 노트북 스탠드" }),
            el("span", { text: "product_id " + data.product_id + " · 출처 " + data.source_ref })
          ])
        ]),
        el("div", { class: "card" }, [
          el("dl", { class: "kv" }, [
            el("dt", { text: "검수 전 필드" }), el("dd", { text: String(data.unresolved_field_count) + "건" }),
            el("dt", { text: "등록 준비 완료 채널" }), el("dd", {
              text: channels.filter(function (c) { return c.ready_for_entry; }).map(function (c) { return c.display_name; }).join(", ") || "없음"
            })
          ]),
          el("div", { class: "toolbar" }, [
            el("button", {
              class: "btn",
              type: "button",
              text: "상세 HTML 내려받기",
              onclick: function () { download("product-detail.html", data.description_html, "text/html;charset=utf-8"); }
            })
          ])
        ])
      ])),
      section("상품 상세정보 HTML 미리보기", "실제 등록 화면에 들어갈 마크업", preview),
      section("판매채널별 등록 초안", null, el("div", {}, [
        channelPicker,
        el("div", { class: "split" }, [
          el("div", { class: "card" }, [
            el("p", { text: active ? active.admin_surface : "" }),
            el("dl", { class: "kv" }, [
              el("dt", { text: "입력 준비" }), el("dd", {}, [statusBadge(active && active.ready_for_entry ? "prepared" : "warn", active && active.ready_for_entry ? "준비됨" : "사람 확인 필요")]),
              el("dt", { text: "검수 전 필드" }), el("dd", { text: String(active ? active.unresolved_field_count : 0) }),
              el("dt", { text: "채널 전용 항목" }), el("dd", { text: String(active ? active.manual_field_count : 0) }),
              el("dt", { text: "규칙 확인일" }), el("dd", { text: active ? active.source_checked_on : "" })
            ])
          ]),
          el("div", { class: "card" }, [el("h3", { text: "차단·주의 항목" }), issueTable])
        ]),
        el("div", { style: "margin-top:14px" }, [fieldTable])
      ])),
      section("이미지 매니페스트", "채널별 이미지 규격은 채널 초안의 issues에 포함", manifestRows.length ? table(
        [
          { key: "role", label: "역할" },
          { key: "file_name", label: "파일" },
          { key: "size", label: "크기" },
          { key: "byte_size", label: "바이트", num: true },
          { key: "alt_text", label: "대체 텍스트" }
        ],
        manifestRows
      ) : el("div", { class: "empty", text: "등록된 이미지가 없습니다." })),
      section("브라우저 입력 계획", "제품이 이미 분류한 액션 어휘 기준", planRows.length ? table(
        [
          { key: "channel", label: "채널" },
          { key: "order", label: "순서", num: true },
          { key: "action", label: "액션" },
          { key: "target_label", label: "대상" },
          { key: "classification", label: "분류" },
          { key: "requires_human", label: "수행 주체" },
          { key: "rationale", label: "근거" }
        ],
        planRows,
        [null, null, null, null, null, function (row) {
          return statusBadge(row.requires_human ? "warn" : "ok", row.requires_human ? "사람" : "자동");
        }, null]
      ) : el("div", { class: "empty", text: "입력 계획이 없습니다." }))
    ]);
  }

  /* ---------------- ERP items ---------------- */

  function renderErp() {
    var data = state.data.erp;
    var filters = [
      { key: "all", label: "전체" },
      { key: "AUTO_OK", label: "정상" },
      { key: "DUPLICATE", label: "중복" },
      { key: "REVIEW_REQUIRED", label: "검토 필요" }
    ];
    var items = data.items.filter(function (item) {
      return state.erpFilter === "all" || item.status === state.erpFilter;
    });

    var rows = items.map(function (item) {
      return {
        item_code: item.item_code || "(코드 없음)",
        item_name: item.item_name,
        model_name: item.model_name,
        supplier: item.supplier,
        purchase_price: item.purchase_price,
        sales_price: item.sales_price,
        status: item.status,
        reasons: item.reasons.join(", ")
      };
    });

    var profileCards = Object.keys(data.profiles).map(function (profileId) {
      var profile = data.profiles[profileId];
      var rowsForProfile = data.field_mapping.filter(function (row) { return row["프로필"] === profileId; });
      var unconfirmed = rowsForProfile.filter(function (row) { return row["확인상태"] !== "CONFIRMED_OFFICIAL"; }).length;
      return card(profileId, null, el("dl", { class: "kv" }, [
        el("dt", { text: "서식 확인" }), el("dd", {}, [statusBadge(profile.template_confirmed ? "prepared" : "warn", profile.template_confirmed ? "확인됨" : "미확인")]),
        el("dt", { text: "업로드 가능" }), el("dd", {}, [statusBadge(profile.upload_ready ? "prepared" : "warn", profile.upload_ready ? "가능" : "불가")]),
        el("dt", { text: "미확인 필드" }), el("dd", { text: String(unconfirmed) + "건" }),
        el("dt", { text: "원문" }), el("dd", { class: "mono", text: profile.raw })
      ]), statusBadge(profile.upload_ready ? "prepared" : "warn", profile.upload_ready ? "업로드 가능" : "업로드 불가"));
    });

    var duplicateRows = data.duplicates.map(function (row) {
      return {
        group: row["중복그룹"],
        type: row["유형"],
        count: row["건수"],
        base: row["기준행"],
        target: row["대상행"],
        similarity: row["유사도"],
        reason: row["사유"]
      };
    });

    var mappingRows = data.field_mapping.map(function (row) {
      return {
        profile: row["프로필"],
        field: row["정규화필드"],
        target: row["대상필드"],
        required: row["필수여부"],
        state: row["확인상태"],
        evidence: row["근거"],
        note: row["비고"]
      };
    });

    var report = data.pipeline_report;

    return el("div", {}, [
      pageHead("ERP 품목관리", "품목 정규화·중복 판정·검토 필요 분류와 Excel 서식 바인딩 결과."),
      el("div", { class: "notice warn", text: data.synthetic_notice }),
      section("처리 요약", null, el("div", { class: "grid cols-3" }, [
        card("건수", "정규화된 품목", el("div", { class: "metrics" }, [
          el("div", { class: "metric" }, [el("span", { text: "행" }), el("strong", { text: String(report.row_count) })])
        ])),
        card("자동 통과", "사람 확인 없이 처리 가능", el("div", { class: "metrics" }, [
          el("div", { class: "metric" }, [el("span", { text: "건" }), el("strong", { text: String(report.auto_ok_count) })])
        ])),
        card("검토 필요", "사람이 확인해야 하는 건", el("div", { class: "metrics" }, [
          el("div", { class: "metric" }, [el("span", { text: "건" }), el("strong", { text: String(report.review_required_count) })])
        ]))
      ])),
      section("품목 데이터", null, el("div", {}, [
        el("div", { class: "toolbar" }, filters.map(function (filter) {
          return el("button", {
            class: "chip",
            type: "button",
            "aria-pressed": state.erpFilter === filter.key ? "true" : "false",
            text: filter.label + " (" + (filter.key === "all" ? data.items.length : data.status_counts[filter.key]) + ")",
            onclick: function () { state.erpFilter = filter.key; render(); }
          });
        }).concat([
          el("span", { class: "spacer" }),
          el("button", {
            class: "btn",
            type: "button",
            text: "필터 결과 CSV 내려받기",
            onclick: function () {
              download("erp-item-master.csv", toCsv(rows, [
                { key: "item_code", label: "품목코드" },
                { key: "item_name", label: "상품명" },
                { key: "model_name", label: "모델명" },
                { key: "supplier", label: "공급사" },
                { key: "purchase_price", label: "매입가" },
                { key: "sales_price", label: "판매가" },
                { key: "status", label: "상태" },
                { key: "reasons", label: "사유" }
              ]), "text/csv;charset=utf-8");
            }
          })
        ])),
        table(
          [
            { key: "item_code", label: "품목코드" },
            { key: "item_name", label: "상품명" },
            { key: "model_name", label: "모델명" },
            { key: "supplier", label: "공급사" },
            { key: "purchase_price", label: "매입가", num: true },
            { key: "sales_price", label: "판매가", num: true },
            { key: "status", label: "상태" },
            { key: "reasons", label: "검토 사유" }
          ],
          rows,
          [null, null, null, null, null, null, function (row) { return statusBadge(row.status); }, null]
        )
      ])),
      section("중복 판정", "중복 그룹별 기준행·대상행", duplicateRows.length ? table(
        [
          { key: "group", label: "그룹" },
          { key: "type", label: "유형" },
          { key: "count", label: "건수", num: true },
          { key: "base", label: "기준행" },
          { key: "target", label: "대상행" },
          { key: "similarity", label: "유사도", num: true },
          { key: "reason", label: "사유" }
        ],
        duplicateRows
      ) : el("div", { class: "empty", text: "중복 그룹이 없습니다." })),
      section("Excel 서식 바인딩", "프로필별 확인 상태", el("div", { class: "grid cols-2" }, profileCards)),
      section("필드 매핑 현황", "프로필별 정규화 필드와 대상 필드", table(
        [
          { key: "profile", label: "프로필" },
          { key: "field", label: "정규화 필드" },
          { key: "target", label: "대상 필드" },
          { key: "required", label: "필수" },
          { key: "state", label: "확인 상태" },
          { key: "evidence", label: "근거" },
          { key: "note", label: "비고" }
        ],
        mappingRows,
        [null, null, null, null, function (row) {
          return statusBadge(row.state === "CONFIRMED_OFFICIAL" ? "prepared" : "warn", row.state === "CONFIRMED_OFFICIAL" ? "확인됨" : row.state);
        }, null, null]
      ))
    ]);
  }

  /* ---------------- order fulfilment ---------------- */

  function renderOrders() {
    var data = state.data.orders;
    var orders = data.orders;
    if (!state.orderId || !orders.some(function (o) { return o.order_id === state.orderId; })) {
      state.orderId = orders.length ? orders[0].order_id : null;
    }
    var active = orders.filter(function (o) { return o.order_id === state.orderId; })[0];
    var lines = data.order_lines.filter(function (line) { return line.order_id === state.orderId; });
    var shipments = data.shipments.filter(function (shipment) { return shipment.order_id === state.orderId; });
    var exceptions = data.exceptions;

    var shipmentTimeline = el("div", { class: "timeline" }, shipments.map(function (shipment) {
      return el("div", { class: "timeline-item" }, [
        el("strong", { text: shipment.status }),
        el("span", { text: shipment.observed_at + (shipment.delivered_at ? " · 배송완료 " + shipment.delivered_at : "") }),
        el("span", { class: "mono", text: shipment.carrier + " " + shipment.tracking_number })
      ]);
    }));

    var stepRows = (data.steps || []).map(function (step) {
      return {
        number: step.number,
        title: step.title_ko,
        automation: step.automation,
        checkpoint: step.human_checkpoint,
        dependency: step.system_dependency
      };
    });

    var probeRows = (data.guard_probes || []).map(function (probe) {
      return { name: probe.name, expected: probe.expected_error, fired: probe.fired };
    });

    var exceptionRows = exceptions.map(function (row) {
      return {
        return_id: row.return_id,
        reason: row.reason,
        status: row.status,
        requested_at: row.requested_at,
        resolution: row.resolution_note
      };
    });

    return el("div", {}, [
      pageHead("주문·배송", "주문 접수 → 발주 초안 → 배송 진행 → 예외 처리. 실제 발주·결제는 수행하지 않았습니다."),
      el("div", { class: "notice warn", text: data.synthetic_notice }),
      section("주문 목록", "가상 주문 1건", el("div", { class: "split" }, [
        el("div", { class: "list" }, orders.map(function (order) {
          return el("button", {
            class: "list-item",
            type: "button",
            "aria-current": order.order_id === state.orderId ? "true" : "false",
            onclick: function () { state.orderId = order.order_id; render(); }
          }, [
            el("strong", { text: order.order_id }),
            el("span", { text: order.channel_order_ref + " · " + order.status + " · 라인 " + order.line_count })
          ]);
        })),
        el("div", { class: "card" }, [
          el("dl", { class: "kv" }, [
            el("dt", { text: "주문 상태" }), el("dd", {}, [statusBadge(active ? active.status : "", active ? active.status : "")]),
            el("dt", { text: "채널 주문번호" }), el("dd", { text: active ? active.channel_order_ref : "" }),
            el("dt", { text: "금액" }), el("dd", { text: active ? active.total_amount_minor + " " + active.currency : "" }),
            el("dt", { text: "배송 상태" }), el("dd", {}, [statusBadge(active ? active.latest_shipment_status : "", active ? active.latest_shipment_status : "없음")]),
            el("dt", { text: "운송장" }), el("dd", { class: "mono", text: active ? active.tracking_number : "" })
          ]),
          el("div", { class: "toolbar" }, [
            el("button", {
              class: "btn",
              type: "button",
              text: "주문 라인 CSV 내려받기",
              onclick: function () {
                download("order-lines.csv", toCsv(lines, Object.keys(lines[0] || {}).map(function (key) { return { key: key, label: key }; })), "text/csv;charset=utf-8");
              }
            }),
            el("button", {
              class: "btn",
              type: "button",
              text: "운송장 입력 템플릿 내려받기",
              onclick: function () {
                download("tracking-input-template.csv", toCsv(data.tracking_template, Object.keys((data.tracking_template[0] || {})).map(function (key) { return { key: key, label: key }; })), "text/csv;charset=utf-8");
              }
            })
          ])
        ])
      ])),
      section("주문 상세", null, table(
        [
          { key: "line_id", label: "라인" },
          { key: "sku", label: "SKU" },
          { key: "description", label: "상품" },
          { key: "quantity", label: "수량", num: true },
          { key: "unit", label: "단위" },
          { key: "unit_price_amount_minor", label: "단가", num: true },
          { key: "line_total_amount_minor", label: "합계", num: true }
        ],
        lines
      )),
      section("공급사 발주 초안", "DRAFT 상태 문서", el("pre", { class: "draft", text: data.supplier_order_draft })),
      section("배송 진행 상태", "운송장 기록", shipmentTimeline),
      section("운송장 기록", null, table(
        [
          { key: "shipment_id", label: "배송 ID" },
          { key: "status", label: "상태" },
          { key: "carrier", label: "운송사" },
          { key: "tracking_number", label: "운송장" },
          { key: "observed_at", label: "관측 시각" },
          { key: "note", label: "비고" }
        ],
        shipments,
        [null, function (row) { return statusBadge(row.status); }, null, null, null, null]
      )),
      section("반품·오배송 예외처리", null, exceptionRows.length ? table(
        [
          { key: "return_id", label: "예외 ID" },
          { key: "reason", label: "사유" },
          { key: "status", label: "상태" },
          { key: "requested_at", label: "요청 시각" },
          { key: "resolution", label: "처리 내용" }
        ],
        exceptionRows,
        [null, null, function (row) { return statusBadge(row.status); }, null, null]
      ) : el("div", { class: "empty", text: "예외 사례가 없습니다." })),
      section("단계별 자동화 구분", null, table(
        [
          { key: "number", label: "단계", num: true },
          { key: "title", label: "단계" },
          { key: "automation", label: "자동화 구분" },
          { key: "checkpoint", label: "사람 확인 지점" },
          { key: "dependency", label: "선행 시스템" }
        ],
        stepRows,
        [null, null, function (row) {
          var kind = row.automation === "fully_automatable" ? "ok" : (row.automation === "human_confirmation_required" ? "warn" : "err");
          var label = row.automation === "fully_automatable" ? "자동 가능" : (row.automation === "human_confirmation_required" ? "사람 확인 필요" : "수동");
          return statusBadge(row.automation, label);
        }, null, null]
      )),
      section("가드 점검", "차단이 의도대로 작동했는지", table(
        [
          { key: "name", label: "점검" },
          { key: "expected", label: "기대 차단" },
          { key: "fired", label: "발동" }
        ],
        probeRows,
        [null, null, function (row) { return statusBadge(row.fired ? "prepared" : "err", row.fired ? "차단됨" : "미차단"); }]
      ))
    ]);
  }

  /* ---------------- remote work demo ---------------- */

  function renderRemote() {
    var data = state.data.remote;
    var contract = data.event_contract;

    return el("div", {}, [
      pageHead("원격업무 시연", "향후 실제 Browser Use 실행 이벤트를 연결할 화면입니다. 지금은 연결되어 있지 않습니다."),
      el("div", { class: "notice warn", text: data.synthetic_notice }),
      section("컴퓨터 연결 상태", null, el("div", { class: "card" }, [
        el("div", { class: "card-top" }, [
          el("h3", { text: data.connection.label }),
          statusBadge("warn", data.connection.state)
        ]),
        el("p", { text: data.connection.detail })
      ])),
      section("현재 실행 중인 업무", null, data.current_job
        ? el("div", { class: "card" }, [el("p", { text: data.current_job })])
        : el("div", { class: "empty", text: "실행 중인 업무가 없습니다." })),
      section("최근 실행 단계", null, data.recent_steps.length
        ? el("div", { class: "timeline" }, data.recent_steps.map(function (step) {
            return el("div", { class: "timeline-item" }, [
              el("strong", { text: step.title }),
              el("span", { text: step.at || "" })
            ]);
          }))
        : el("div", { class: "empty", text: "실행 단계 기록이 없습니다." })),
      section("스크린샷·실행 증거", null, data.screenshots.length
        ? el("div", { class: "grid cols-3" }, data.screenshots.map(function (shot) {
            return el("div", { class: "card" }, [el("p", { text: shot.label || shot.ref || "" })]);
          }))
        : el("div", { class: "empty", text: "스크린샷 증거가 없습니다. 실제 실행이 연결되면 이 영역에 표시됩니다." })),
      section("마우스·클릭·스크롤 실행 기록", null, data.input_events.length
        ? table(
            [
              { key: "action", label: "액션" },
              { key: "target", label: "대상" },
              { key: "at", label: "시각" }
            ],
            data.input_events
          )
        : el("div", { class: "empty", text: "입력 이벤트 기록이 없습니다. 실제 실행이 연결되면 이 영역에 표시됩니다." })),
      section("연결할 이벤트 계약", "제품이 이미 분류한 액션 어휘", el("div", { class: "grid cols-3" }, [
        card("lease 허용", "자동 입력 가능", el("ul", {}, contract.lease_eligible_actions.map(function (action) { return el("li", { class: "mono", text: action }); }))),
        card("단계승인 필요", "사람이 수행", el("ul", {}, contract.step_up_required_actions.map(function (action) { return el("li", { class: "mono", text: action }); })), statusBadge("warn", "사람 수행")),
        card("금지", "수행하지 않음", el("ul", {}, contract.prohibited_actions.map(function (action) { return el("li", { class: "mono", text: action }); })), statusBadge("err", "금지"))
      ]))
    ]);
  }

  /* ---------------- router ---------------- */

  var ROUTES = {
    dashboard: renderDashboard,
    product: renderProduct,
    erp: renderErp,
    orders: renderOrders,
    remote: renderRemote
  };

  function currentRoute() {
    var hash = (window.location.hash || "").replace(/^#\/?/, "").split("?")[0];
    return ROUTES[hash] ? hash : "dashboard";
  }

  function render() {
    state.route = currentRoute();
    var link = document.querySelector('[data-nav="' + state.route + '"]');
    if (link) { link.setAttribute("aria-current", "page"); }
    Array.prototype.forEach.call(document.querySelectorAll(".nav a"), function (node) {
      if (node.getAttribute("data-nav") !== state.route) { node.removeAttribute("aria-current"); }
    });
    view.textContent = "";
    view.appendChild(ROUTES[state.route]());
  }

  function fail(message) {
    view.textContent = "";
    view.appendChild(el("div", { class: "notice warn", text: message }));
  }

  function load() {
    var keys = Object.keys(DATA);
    Promise.all(keys.map(function (key) {
      return fetch("./data/" + DATA[key], { cache: "no-store" })
        .then(function (response) {
          if (!response.ok) { throw new Error(DATA[key] + " 로드 실패 (HTTP " + response.status + ")"); }
          return response.json();
        })
        .then(function (payload) { state.data[key] = payload; });
    })).then(function () {
      var synthetic = Object.keys(state.data).some(function (key) { return state.data[key].synthetic_data; });
      document.getElementById("synthetic-badge").hidden = !synthetic;
      render();
    }).catch(function (error) {
      fail("데이터를 불러오지 못했습니다: " + error.message);
    });
  }

  window.addEventListener("hashchange", render);
  load();
})();
