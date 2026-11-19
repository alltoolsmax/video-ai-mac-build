<?php
// Video AI - Mr. Huỳnh · cấu hình máy chủ bản quyền (dùng chung hosting với Voice AI).
// Sao chép file này thành config.php (cùng thư mục) rồi điền. KHÔNG đặt trong thư mục công khai.
return [
    // "Con dấu" ký giấy phép Video AI: 64 ký tự hex trong file video_seed.hex (do tools/make_license_keys.py tạo).
    // KHÁC với seed của Voice AI. Không gửi cho ai.
    'seed_hex' => 'DAN_NOI_DUNG_video_seed.hex_VAO_DAY',

    // Mật khẩu đăng nhập trang quản trị chung https://active.mrhuynh.net/admin/ (đặt chuỗi dài, khó đoán)
    'admin_password' => 'DAT_MAT_KHAU_QUAN_TRI_DAI',

    // Để trống = dùng chung của Voice AI (active_private/config.php): sepay_api_key, bank, telegram, code_prefix
    'sepay_api_key'    => '',
    'telegram_token'   => '',
    'telegram_chat_id' => '',
    'bank'             => null,     // vd ['bin' => '970418', 'name' => 'BIDV', 'account' => '...', 'holder' => '...']

    // Bảng giá mặc định gói Chuyên nghiệp (sửa tiếp trong trang quản trị, không cần sửa ở đây)
    'plans' => [
        'm1' => ['name' => '1 tháng', 'days' => 30,  'price' => 80000,  'badge' => null],
        'm3' => ['name' => '3 tháng', 'days' => 90,  'price' => 220000, 'badge' => 'Phổ biến'],
        'm6' => ['name' => '6 tháng', 'days' => 180, 'price' => 450000, 'badge' => 'Tiết kiệm 30.000đ'],
        'y1' => ['name' => '1 năm',   'days' => 365, 'price' => 900000, 'badge' => 'Tiết kiệm 60.000đ'],
    ],

    'contact_zalo'  => 'https://zalo.me/0979007367',
    'contact_phone' => '0979007367',
    'contact_name'  => 'Mr. Huỳnh',

    'order_ttl_minutes'      => 30,   // đơn chờ thanh toán hết hạn sau
    'transfer_cooldown_days' => 30,   // khách tự chuyển key sang máy mới: 1 lần / N ngày
    'recheck_hours'          => 24,   // phần mềm kiểm tra lại bản quyền sau
    'offline_grace_days'     => 3,    // dùng không mạng tối đa
    'timezone'               => 'Asia/Ho_Chi_Minh',
];
