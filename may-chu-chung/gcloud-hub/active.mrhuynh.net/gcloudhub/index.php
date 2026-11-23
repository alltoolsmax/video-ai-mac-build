<?php
declare(strict_types=1);
// API cập nhật GCloud Hub - Mr. Huỳnh:  /gcloudhub/v1/app/version  ·  /gcloudhub/v1/ping
// GCloud Hub miễn phí, không có key. Endpoint này chỉ phục vụ kiểm tra & tải bản cập nhật.
require (getenv('GCLOUDHUB_PRIVATE') ?: __DIR__ . '/../../active_private/gcloudhub') . '/lib.php';

use function GCloudHub\{api_version, client_ip, fail, json_out, limited, log_line};

try {
    $path = (string)parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    $pos = strpos($path, '/v1/');
    $route = $pos === false ? '' : rtrim(substr($path, $pos), '/');

    if ($route === '') {
        header('Content-Type: text/plain; charset=utf-8');
        echo "GCloud Hub - Mr. Huynh update server\n";
        exit;
    }
    if (limited('api:' . client_ip(), 60)) {
        fail('rate', 'Bạn thao tác quá nhanh, thử lại sau 1 phút.', 429);
    }
    if ($route === '/v1/app/version') {
        api_version();                  // GET ?os=win&iid=<id ngẫu nhiên>&v=<phiên bản hiện tại>
    }
    if ($route === '/v1/ping') {
        api_version();                  // alias
    }
    fail('not_found', 'Không có', 404);
} catch (Throwable $e) {
    log_line('gcloudhub/index.php: ' . $e->getMessage());
    json_out(['ok' => false, 'code' => 'server', 'message' => 'Lỗi máy chủ, vui lòng thử lại sau.'], 500);
}
