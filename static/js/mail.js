$(document).ready(function () {
    var clipboard = new Clipboard('.copyable');
    clipboard.on('success', function (e) {
        console.info('copy address:', e.text);
        $.uiAlert({
            textHead: '复制成功',
            text: e.text,
            bgcolor: '#2ecc71',
            textcolor: '#fff',
            position: 'top-right',
            time: 1.2
        });
    });
    clipboard.on('error', function (e) {
        $.uiAlert({
            textHead: '复制失败',
            text: '无法复制文本，请手动复制',
            bgcolor: '#e74c3c',
            textcolor: '#fff',
            position: 'top-right',
            time: 1.2
        });
    });

    document.querySelector('iframe').addEventListener('load', function () {
        var iframeBody = this.contentWindow.document.body;
        var height = Math.max(iframeBody.scrollHeight, iframeBody.offsetHeight);
        this.style.height = `${height}px`;
        console.log("iframe h: " + height);
    });

    var UUID = null;

    function setAddress(uuid, domain) {
        $("#address")[0].value = uuid + "@" + domain;
        $('#address').parent().attr('data-clipboard-text', uuid + "@" + domain);
        $('#rss-link').attr('data-clipboard-text', (window.location.origin + window.location.pathname + "/mail/" + uuid + "/rss").replace(RegExp('//mail/', 'g'), "/mail/"));
    }

    function adjustSize() {
        $("#content-iframe").height($("#content-iframe").contents().height());
    }

    function showDetail(id) {
        if (!UUID) {
            console.error("UUID 未定义，无法加载邮件详情");
            return;
        }
        $.ajax({
            type: "GET",
            url: "/mail/" + UUID + "/" + id,
            success: function (msg) {
                $("#subject").text("主题：" + msg.subject);
                $("#content-iframe").attr('src', '/mail/' + UUID + '/' + id + '/iframe');
                $("#newtab").attr("href", '/mail/' + UUID + '/' + id + '/show');
                $("#newtab").attr("target", "_blank");
            },
            error: function (msg) {
                console.log("无法加载邮件详情：", msg);
            }
        });
    }

    function setIntervalImmed(func, interval) {
        func();
        return setInterval(func, interval);
    }

    $("#releaseAddress").click(function () {
        $.ajax({
            type: "DELETE",
            dataType: "text",
            url: "/user/" + UUID,
            success: function (msg) {
                $.uiAlert({
                    textHead: '删除成功',
                    text: '邮箱及数据已删除，正在分配新邮箱',
                    bgcolor: '#e74c3c',
                    textcolor: '#fff',
                    position: 'top-right',
                    time: 1.0
                });
                setTimeout(function () {
                    window.location.reload();
                }, 1000);
            },
            error: function (msg) {
                window.location.reload();
            }
        });
    });

    // 初始化后缀选择框
    function initializeDomainDropdown() {
        var $dropdown = $('#domainDropdown');
        $.ajax({
            type: "GET",
            url: "/domains",
            success: function (domains) {
                $dropdown.find('.menu').empty();  // 清空现有选项
                domains.forEach(function (domain) {
                    var $item = $('<div class="item" data-value="' + domain + '">' + domain + '</div>');
                    $dropdown.find('.menu').append($item);
                });
                $dropdown.dropdown(); // 初始化下拉菜单
            },
            error: function (msg) {
                console.error("Failed to load domains:", msg);
            }
        });
    }

    // 处理自定义邮箱按钮
    $("#customizeEmail").click(function () {
        var customEmail = $("#customEmailInput").val().trim();  // 获取自定义邮箱名
        var selectedDomain = $('#domainDropdown').dropdown('get value');  // 获取选中的后缀
        if (customEmail && selectedDomain) {
            $.ajax({
                type: "POST",
                url: "/user/custom",
                data: JSON.stringify({ uuid: customEmail, domain: selectedDomain }),  // 发送自定义UUID和后缀
                contentType: "application/json",  // 指定请求体内容类型
                success: function (msg) {
                    UUID = msg.uuid;  // 设置新的UUID
                    setAddress(UUID, selectedDomain);
                    loadMailList();  // 加载邮件列表
                },
                error: function (msg) {
                    console.log(msg);
                }
            });
        } else {
            alert('请输入邮箱名和选择后缀');
        }
    });

    // 处理随机邮箱按钮
    $("#generateRandomEmail").click(function () {
        $.ajax({
            type: "POST",
            url: "/user/random",
            contentType: "application/json",  // 指定请求体内容类型
            success: function (msg) {
                UUID = msg.uuid;  // 设置新的UUID
                var selectedDomain = $('#domainDropdown').dropdown('get value') || '';  // 获取选中的后缀或空
                setAddress(UUID, selectedDomain);
                loadMailList();  // 加载邮件列表
            },
            error: function (msg) {
                console.log(msg);
            }
        });
    });

    function loadMailList() {
        if (!UUID) {
            console.error("UUID 未定义，无法加载邮件列表");
            return;
        }
        $.ajax({
            type: "GET",
            url: "/mail/" + UUID,
            success: function (msg) {
                var $maillist = $("#maillist");
                $maillist.html("");  // 清空当前邮件列表
                if (msg.length) {
                    msg.forEach(function (mail) {
                        var $tr = $('<tr>').attr('id', 'mail-' + mail.id);
                        $tr.append($('<td>').text(mail.sender))
                           .append($('<td>').text(mail.subject || '无主题'))
                           .append($('<td>').text(mail.create_time));
                        $maillist.append($tr);
                    });
                } else {
                    $maillist.html('<p style="margin: 1em">暂无邮件可以显示。</p>');
                }
            },
            error: function (msg) {
                console.log(msg);
            }
        });
    }

    // 使用事件委托来绑定事件
    $('#maillist').on('click', 'tr', function() {
        var id = $(this).attr('id').split('-')[1];
        showDetail(id);
    });

    // 初始化域名选择框和邮箱地址
    $.ajax({
        type: "GET",
        url: "/domains",
        success: function (domains) {
            initializeDomainDropdown();  // 初始化后缀选择框
            if (domains.length > 0) {
                setAddress(UUID || "", domains[0]);  // 设置默认域名为空
            }
            setIntervalImmed(loadMailList, 1678);  // 间隔时间
            setInterval(function () {
                $.ajax({
                    type: "GET",
                    url: "/domains",
                });
            }, 60 * 1000);
        },
        error: function (msg) {
            console.log(msg);
        }
    });
});
