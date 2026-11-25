<?php
defined('ABSPATH') || exit;

if ('local' !== wp_get_environment_type() || !defined('TOP_PARIKS_STORE003_CAPTURE') || !TOP_PARIKS_STORE003_CAPTURE) {
    return;
}

// Test runner reads the latest message for its own example.test address via WP-CLI.
add_filter('pre_wp_mail', static function ($result, $message) {
    $recipients = (array) ($message['to'] ?? []);
    if (count($recipients) === 1) {
        $recipient = strtolower(trim(reset($recipients)));
        if (is_email($recipient) && substr($recipient, -13) === '@example.test') {
            set_transient('topqa_mail_' . hash('sha256', $recipient), [
                'subject' => (string) $message['subject'],
                'message' => (string) $message['message'],
            ], 10 * MINUTE_IN_SECONDS);
        }
    }
    return true;
}, 20, 2);
