# Browser Verification Report

Overall: PASS

## External Font/Icon CDN Check
- Result: PASS - none found

## CSS @import Check
- Result: PASS

## Horizontal Overflow Check
- 390x844: PASS (scrollWidth=390, clientWidth=390)
- 768x1024: PASS (scrollWidth=768, clientWidth=768)
- 1440x1100: PASS (scrollWidth=1440, clientWidth=1440)

## Page-Level Checks
### korean_home (/)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS
### english_home (/en/)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS
### korean_topic_feed (/topics/pv-topic-0001/)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS
### korean_record_detail (/records/pv-rec-0001/)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS
### korean_topics_list (/topics/)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS
### korean_records_search (/records)
- Console errors: 0 PASS
- Broken images: 0 PASS
- Focus-visible: PASS

## Contrast Check (WCAG 2.1 AA)
- General text: >= 4.5:1
- Large text (>= 18px or >= 14px bold): >= 3:1
- Only elements with direct text content are checked
- Transparent backgrounds resolved by walking up DOM to nearest opaque ancestor

### korean_home (/)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

### english_home (/en/)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

### korean_topic_feed (/topics/pv-topic-0001/)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

### korean_record_detail (/records/pv-rec-0001/)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

### korean_topics_list (/topics/)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

### korean_records_search (/records)
- Minimum ratio: all >= 4.5
  - All text passes contrast requirements

## YouTube Link Safety
- https://www.youtube.com/watch?v=aircAruvnKk: target=_blank rel=noopener noreferrer PASS
- https://www.youtube.com/watch?v=aircAruvnKk: target=_blank rel=noopener noreferrer PASS

## Filter State Pages
- State 'all': active_pill=전체 PASS
- State 'unseen': active_pill=아직 보지 않음 PASS
- State 'opened': active_pill=열어봄 PASS
- State 'saved': active_pill=저장함 PASS
- State 'in_progress': active_pill=보는 중 PASS
- State 'completed': active_pill=다 봄 PASS
- State 'revisit': active_pill=다시 보기 PASS
- State 'irrelevant': active_pill=관심 없음 PASS

## Internal Link Integrity
- Total internal links found: 25
- Result: PASS (links are static file references)
