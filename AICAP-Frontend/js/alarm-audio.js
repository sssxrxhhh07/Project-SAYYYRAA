/* ============================================================
   alarm-audio.js — Alarm Audio & Notification System
   Handles audio playback, browser notifications, and alarm triggering
   ============================================================ */

/* ---------- Audio Controller ---------- */

const AlarmAudio = {
  audioElement: null,
  isPlaying: false,
  currentAlarmId: null,
  autoplayEnabled: false,

  /**
   * Initialize the audio system
   * Must be called after a user gesture to enable autoplay
   */
  init() {
    this.audioElement = document.getElementById('alarmAudio');
    if (!this.audioElement) {
      console.error('Alarm audio element not found');
      return false;
    }

    // Request notification permission
    this.requestNotificationPermission();

    // Enable audio after user interaction
    this.enableAutoplay();
    
    return true;
  },

  /**
   * Enable audio playback by triggering a short silent play
   * This unlocks audio in browsers that require user gesture
   */
  enableAutoplay() {
    try {
      const audio = this.audioElement;
      audio.volume = 0; // Silent
      audio.play().then(() => {
        audio.pause();
        audio.currentTime = 0;
        audio.volume = 1; // Restore volume
        this.autoplayEnabled = true;
        console.log('Audio autoplay enabled');
      }).catch(err => {
        console.warn('Could not enable autoplay:', err);
      });
    } catch (err) {
      console.warn('Autoplay enable failed:', err);
    }
  },

  /**
   * Request browser notification permission
   */
  requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      // Show a prompt to user
      const notificationPrompt = document.createElement('div');
      notificationPrompt.className = 'callout callout-tip';
      notificationPrompt.style.position = 'fixed';
      notificationPrompt.style.bottom = 'var(--space-6)';
      notificationPrompt.style.left = '50%';
      notificationPrompt.style.transform = 'translateX(-50%)';
      notificationPrompt.style.zIndex = 'var(--z-toast)';
      notificationPrompt.style.maxWidth = '400px';
      notificationPrompt.innerHTML = `
        <span aria-hidden="true">🔔</span>
        <span>Turn on notifications so AICAP can actually wake you up — even with the tab in the background.</span>
        <div style="margin-top: var(--space-3);">
          <button type="button" class="btn btn-primary btn-sm" onclick="this.parentElement.parentElement.remove(); AlarmAudio.enableNotifications()">Turn on</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="this.parentElement.parentElement.remove()">Not now</button>
        </div>
      `;
      document.body.appendChild(notificationPrompt);
    }
  },

  enableNotifications() {
    Notification.requestPermission().then(permission => {
      console.log('Notification permission:', permission);
      if (permission === 'granted') {
        showToast('Notifications turned on', 'success');
      } else {
        showToast('Notifications blocked', 'warning');
      }
    });
  },

  /**
   * Play alarm sound with notification
   * @param {Object} alarm - Alarm object with id, title, etc.
   */
  play(alarm) {
    if (!this.audioElement) {
      console.error('Audio element not initialized');
      return;
    }

    this.currentAlarmId = alarm.id;
    
    // Vibrate if supported and alarm has vibration enabled
    if (alarm.vibration && 'vibrate' in navigator) {
      navigator.vibrate([200, 100, 200]); // Vibration pattern
    }
    
    // Play audio
    try {
      this.audioElement.currentTime = 0;
      this.audioElement.play().then(() => {
        this.isPlaying = true;
        console.log('Alarm audio playing:', alarm.title);
      }).catch(err => {
        console.error('Audio play failed:', err);
        // Fallback to notification only if audio fails
        this.showNotification(alarm);
      });
    } catch (err) {
      console.error('Audio play error:', err);
      this.showNotification(alarm);
    }

    // Always show notification as fallback/companion
    this.showNotification(alarm);
  },

  /**
   * Stop alarm sound
   */
  stop() {
    if (this.audioElement && this.isPlaying) {
      this.audioElement.pause();
      this.audioElement.currentTime = 0;
      this.isPlaying = false;
      this.currentAlarmId = null;
      console.log('Alarm audio stopped');
    }
  },

  /**
   * Show browser notification for alarm
   * 
   * IMPORTANT LIMITATION: This browser Notification API implementation does NOT cover:
   * - Tab-closed scenarios (when the user has closed the browser tab)
   * - Phone-locked scenarios (when the device is locked)
   * 
   * To cover those cases, you would need:
   * - Native shell integration (for mobile apps)
   * - Web Push + Service Worker (for web apps)
   * 
   * Those solutions are out of scope for this implementation, which focuses on
   * in-browser alarm triggering when the tab is open (foreground or backgrounded).
   */
  showNotification(alarm) {
    if (!('Notification' in window)) {
      console.log('Notifications not supported');
      return;
    }

    if (Notification.permission === 'granted') {
      const notification = new Notification('AICAP Alarm', {
        body: `${alarm.title} - ${alarm.alarm_time}`,
        icon: '/favicon.ico', // Replace with actual icon if available
        tag: `alarm-${alarm.id}`,
        requireInteraction: true,
      });

      notification.onclick = () => {
        window.focus();
        notification.close();
        // Handle notification click - could open snooze/dismiss modal
        this.handleAlarmAction(alarm.id, 'dismiss');
      };
    } else if (Notification.permission !== 'denied') {
      // Request permission and try again
      Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
          this.showNotification(alarm);
        }
      });
    }
  },

  /**
   * Handle alarm action (dismiss/snooze)
   * @param {number} alarmId - ID of the alarm
   * @param {string} action - 'dismiss' or 'snooze'
   */
  async handleAlarmAction(alarmId, action) {
    console.log(`Alarm ${alarmId} ${action}ed`);
    this.stop();
    
    // Hide the alarm trigger overlay
    const overlay = document.getElementById('alarmTriggerOverlay');
    if (overlay) {
      overlay.classList.add('hidden');
    }
    
    // Here you would call the appropriate API endpoint
    if (action === 'dismiss') {
      try {
        // Disable the alarm after dismissal
        if (typeof disableAlarm === 'function') {
          await disableAlarm(alarmId);
          showToast('Gone for good.', 'success');
        }
      } catch (err) {
        console.error('Failed to disable alarm:', err);
        showToast('Gone for good (update failed)', 'warning');
      }
    } else if (action === 'snooze') {
      // Implement snooze logic - typically 5 minutes
      // This would require updating the alarm time in the backend
      console.log('Snooze functionality would update alarm time +5 minutes');
      showToast('Snoozed. We\'ll remember that.', 'info');
    }
  },

  /**
   * Check if audio is currently playing
   */
  isActive() {
    return this.isPlaying;
  },

  /**
   * Get the currently playing alarm ID
   */
  getCurrentAlarmId() {
    return this.currentAlarmId;
  }
};

/* ---------- Alarm Monitoring System ---------- */

const AlarmMonitor = {
  checkInterval: null,
  isActive: false,
  checkIntervalMs: 1000, // Check every second

  /**
   * Start monitoring for alarms
   */
  start() {
    if (this.isActive) return;
    
    this.isActive = true;
    this.checkInterval = setInterval(() => {
      this.checkAlarms();
    }, this.checkIntervalMs);
    
    console.log('Alarm monitoring started');
  },

  /**
   * Stop monitoring for alarms
   */
  stop() {
    if (!this.isActive) return;
    
    this.isActive = false;
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
    
    console.log('Alarm monitoring stopped');
  },

  /**
   * Check if any alarms should trigger now
   */
  async checkAlarms() {
    try {
      // Only check if user is logged in
      if (!localStorage.getItem('access_token')) {
        return;
      }

      // Get today's alarms
      const todayAlarms = await fetchTodayAlarms();
      if (!todayAlarms || todayAlarms.length === 0) {
        return;
      }

      const now = new Date();
      const currentTime = now.toTimeString().slice(0, 5); // HH:MM format
      const currentSeconds = now.getSeconds();

      // Check each alarm
      for (const alarm of todayAlarms) {
        if (!alarm.is_active) continue;

        // Check if alarm time matches current time (within the same minute)
        if (alarm.alarm_time === currentTime && currentSeconds < 5) {
          // Avoid triggering multiple times in the same minute
          const lastTriggerKey = `alarm_triggered_${alarm.id}_${alarm.alarm_time}`;
          const lastTrigger = localStorage.getItem(lastTriggerKey);
          const currentMinute = Math.floor(now.getTime() / 60000);
          
          if (lastTrigger !== currentMinute.toString()) {
            localStorage.setItem(lastTriggerKey, currentMinute.toString());
            this.triggerAlarm(alarm);
          }
        }
      }
    } catch (err) {
      console.error('Error checking alarms:', err);
    }
  },

  /**
   * Trigger an alarm
   */
  triggerAlarm(alarm) {
    console.log('Triggering alarm:', alarm.title);
    
    // Record alarm start time for dismiss tracking
    alarmStartTime = Date.now();
    
    // For SMART_ADAPTIVE alarms, show the adaptive time
    let displayTime = alarm.alarm_time;
    if (alarm.alarm_type === 'SMART_ADAPTIVE' && alarm.adaptive_offset !== 0) {
      const offsetSign = alarm.adaptive_offset > 0 ? '+' : '';
      displayTime = `${alarm.alarm_time} (${offsetSign}${alarm.adaptive_offset}min)`;
    }
    
    // Check if alarm has custom sound setting
    const soundFile = alarm.sound && alarm.sound !== 'default' 
      ? `audio/${alarm.sound}.wav` 
      : 'audio/default-alarm.wav';
    
    // Update audio source if custom sound
    if (AlarmAudio.audioElement && soundFile !== AlarmAudio.audioElement.src) {
      AlarmAudio.audioElement.src = soundFile;
    }
    
    // Ensure vibration is properly set (default to true if not specified)
    if (alarm.vibration === undefined || alarm.vibration === null) {
      alarm.vibration = true;
    }
    
    // Play alarm
    AlarmAudio.play(alarm);
    
    // Show alarm trigger overlay
    const overlay = document.getElementById('alarmTriggerOverlay');
    const message = document.getElementById('alarmTriggerMessage');
    if (overlay) {
      overlay.classList.remove('hidden');
      if (message) {
        message.textContent = `${alarm.title} - ${displayTime}`;
      }
    }
    
    // Show toast notification
    showToast(`Alarm: ${alarm.title}`, 'info');
  }
};

/* ---------- Global Alarm Action Functions ---------- */

// Track when alarm started ringing for dismiss time calculation
let alarmStartTime = null;

/**
 * Dismiss the currently ringing alarm
 */
async function dismissAlarm() {
  const alarmId = AlarmAudio.getCurrentAlarmId();
  if (alarmId) {
    // Calculate time to dismiss
    const secondsToDismiss = alarmStartTime ? 
      Math.floor((Date.now() - alarmStartTime) / 1000) : 0;
    
    try {
      // Call the real dismiss API using the API function from alarms.js
      await apiFetch(`/alarms/${alarmId}/dismiss`, { 
        method: "POST", 
        body: { seconds_to_dismiss: secondsToDismiss } 
      });
      
      AlarmAudio.handleAlarmAction(alarmId, 'dismiss');
      showToast('I\'m up', 'success');
    } catch (err) {
      console.error('Failed to dismiss alarm:', err);
      AlarmAudio.handleAlarmAction(alarmId, 'dismiss'); // Still stop audio
      showToast('I\'m up (update failed)', 'warning');
    }
  } else {
    // Fallback if no alarm ID is tracked
    AlarmAudio.stop();
    const overlay = document.getElementById('alarmTriggerOverlay');
    if (overlay) {
      overlay.classList.add('hidden');
    }
  }
}

/**
 * Snooze the currently ringing alarm for 5 minutes
 */
async function snoozeAlarm() {
  const alarmId = AlarmAudio.getCurrentAlarmId();
  if (alarmId) {
    try {
      // Call the real snooze API
      await apiFetch(`/alarms/${alarmId}/snooze`, { 
        method: "PATCH", 
        body: { snooze_minutes: 5 } 
      });
      
      AlarmAudio.handleAlarmAction(alarmId, 'snooze');
      showToast('Snoozed. We\'ll remember that.', 'success');
    } catch (err) {
      console.error('Failed to snooze alarm:', err);
      AlarmAudio.handleAlarmAction(alarmId, 'snooze'); // Still stop audio
      showToast('Snoozed (update failed)', 'warning');
    }
  } else {
    // Fallback if no alarm ID is tracked
    AlarmAudio.stop();
    const overlay = document.getElementById('alarmTriggerOverlay');
    if (overlay) {
      overlay.classList.add('hidden');
    }
    showToast('Snoozed. We\'ll remember that.', 'info');
  }
}

/* ---------- Initialization ---------- */

// Initialize alarm audio system when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  // Initialize audio on first user interaction
  const initAudio = () => {
    AlarmAudio.init();
    // Remove event listener after first interaction
    document.removeEventListener('click', initAudio);
    document.removeEventListener('keydown', initAudio);
  };

  document.addEventListener('click', initAudio);
  document.addEventListener('keydown', initAudio);

  // Start alarm monitoring if user is logged in
  if (localStorage.getItem('access_token')) {
    AlarmMonitor.start();
  }
});

// Start/stop monitoring based on authentication state
const originalLoginUser = window.loginUser;
if (originalLoginUser) {
  window.loginUser = async function(...args) {
    const result = await originalLoginUser.apply(this, args);
    AlarmMonitor.start();
    return result;
  };
}

const originalLogoutUser = window.logoutUser;
if (originalLogoutUser) {
  window.logoutUser = function(...args) {
    AlarmMonitor.stop();
    AlarmAudio.stop();
    return originalLogoutUser.apply(this, args);
  };
}
