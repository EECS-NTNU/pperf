#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <libgen.h>
#include <stdbool.h>

#define VMMAP_LABEL_LENGTH 255
#define STRINGIFY_EVAL(x) #x
#define STRINGIFY(x) STRINGIFY_EVAL(x)

struct VMMap {
    uint64_t addr;
    uint64_t size;
    char label[VMMAP_LABEL_LENGTH + 1];
} __attribute__((packed));

struct VMMaps {
    uint32_t count;
    struct VMMap *maps;
};

bool containsMap(struct VMMaps const maps, uint64_t const saddr, uint64_t const eaddr , char const * const label) {
  for (unsigned int i = 0; i < maps.count; i++) {
    if (maps.maps[i].addr == saddr && maps.maps[i].size == (eaddr - saddr) && strcmp(maps.maps[i].label, label) == 0)
      return true;
  }
  return false;
}

void getProcessVMMaps(struct VMMaps *result, pid_t pid, unsigned int const limit) {
    unsigned int freeAllocated = 0;
    if (result == NULL)
      return;

    char procmap[256];

    if (snprintf(procmap, 256,"/proc/%d/maps", pid) <= 0) {
        fprintf(stderr, "/proc/%d/maps did not fit into buffer\n", pid);
    }

    FILE *pmap = fopen(procmap, "r");
    while (!feof(pmap)) {
        uint64_t saddr = 0, eaddr = 0, offset = 0;
        char ex = '\0';
        char path[1024] = {};
        int res;

        res = fscanf(pmap, "%lx-%lx %*c%*c%c%*c %lx %*[^ ] %*[^ ] %1023s\n", &saddr, &eaddr, &ex, &offset, path);
        // Just continue if we have found all 5 values
        if (res == 5) {
          char *filename = basename(path);
          // check for execute bit and ignore special files/decives
          if (ex == 'x' && !(filename[0] == '[' && filename[strlen(filename) - 1] == ']')) {
            if (!containsMap(*result, saddr, eaddr, filename)) {
              if (result->count == 0) {
                result->maps = (struct VMMap *) malloc(sizeof(struct VMMap));
                freeAllocated = 1;
              } else if (freeAllocated == 0) {
                result->maps = (struct VMMap *) realloc(result->maps, 2 * result->count * sizeof(struct VMMap));
                freeAllocated = result->count;
              }
              if (result->maps == NULL) {
                result->count = 0;
                break;
              }

              result->maps[result->count].addr = saddr;
              result->maps[result->count].size = eaddr - saddr;
              memcpy(result->maps[result->count].label, filename, strlen(filename));

              result->count++;
              freeAllocated--;

              if (limit == result->count)
                break;
            }
          }
        } else {
          // Discard invalid line
          res = fscanf(pmap, "%*[^\n]\n");
        }
    }
    fclose(pmap);
    if (result->count > 0 && freeAllocated > 0) {
      result->maps = (struct VMMap *) realloc(result->maps, result->count * sizeof(struct VMMap));
      if (result->maps == NULL)
        result->count = 0;
    }
}

void freeVMMaps(struct VMMaps *maps) {
  if (maps->maps != NULL) {
    free(maps->maps);
    maps->maps = NULL;
  }
  maps->count = 0;
}

void dumpVMMaps(char const * const prefix, struct VMMaps const maps) {
  for (unsigned int i = 0; i < maps.count; i++) {
    printf("%s%02u: 0x%lx - 0x%lx - %s\n", prefix, i, maps.maps[i].addr, maps.maps[i].size, maps.maps[i].label);
  }
}

int VMMapCollision(struct VMMaps *map1, struct VMMaps *map2) {
  for (unsigned int i = 0; i < map1->count; i++) {
    uint64_t const m1start = map1->maps[i].addr;
    uint64_t const m1end = m1start + map1->maps[i].size;
    for (unsigned int j = 0; j < map2->count; j++) {
      uint64_t const m2start = map2->maps[j].addr;
      uint64_t const m2end = m2start + map2->maps[j].size;
      if (m1start >= m2start && m1start < m2end) return 1;
      if (m1end >= m2start && m1end < m2end) return 1;
    }
  }
  return 0;
}
