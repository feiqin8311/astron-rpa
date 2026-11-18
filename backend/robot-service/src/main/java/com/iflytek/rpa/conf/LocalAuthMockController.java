package com.iflytek.rpa.conf;

import com.iflytek.rpa.common.feign.entity.User;
import com.iflytek.rpa.common.feign.entity.dto.RoleBaseDto;
import com.iflytek.rpa.common.feign.entity.dto.UserExtendDto;
import com.iflytek.rpa.utils.response.AppResponse;
import java.util.Collections;
import java.util.List;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 单机离线模式下的本地身份与会话 Mock 控制器。
 * 当配置 auth.enabled=false 时激活，接管 RpaAuthFeign 的用户与会话查询，
 * 为后端提供稳定的本地管理员上下文，避免依赖独立的 rpa-auth 与 Casdoor 容器。
 */
@RestController
@RequestMapping("/api/rpa-auth")
@ConditionalOnProperty(name = "auth.enabled", havingValue = "false")
public class LocalAuthMockController {

    private User createLocalUser() {
        User user = new User();
        user.setId("local-user");
        user.setName("本地用户");
        user.setLoginName("admin");
        user.setOrgId("default");
        user.setOrgName("默认组织");
        user.setStatus(1);
        return user;
    }

    @GetMapping("/user/info")
    public AppResponse<User> getLoginUser() {
        return AppResponse.success(createLocalUser());
    }

    @PostMapping("/user/getUserExtendInfo")
    public AppResponse<UserExtendDto> getUserExtendInfo(
            @RequestParam(value = "tenantId", required = false) String tenantId) {
        UserExtendDto dto = new UserExtendDto();
        dto.setUser(createLocalUser());
        RoleBaseDto adminRole = new RoleBaseDto();
        adminRole.setId("admin");
        adminRole.setName("管理员");
        dto.setRoles(Collections.singletonList(adminRole));
        return AppResponse.success(dto);
    }

    @GetMapping("/check-session")
    public AppResponse<String> checkSession() {
        return AppResponse.success("ok");
    }

    @GetMapping("/user/queryAllListByOrgId")
    public AppResponse<List<User>> queryAllListByOrgId(
            @RequestParam(value = "orgId", required = false) String orgId) {
        return AppResponse.success(Collections.singletonList(createLocalUser()));
    }
}
